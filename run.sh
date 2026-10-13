#!/usr/bin/env bash
# Запуск приложения и проверок на текущей тестовой БД.
set -Eeuo pipefail

PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$PROJECT_DIR"

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  cat <<'HELP'
Использование: ./run.sh

Собирает образ, запускает Compose, выполняет Ruff, pytest и интеграционные проверки.
На время проверки восстановления останавливает RabbitMQ и запускает его обратно.
Использует текущую БД из .env, добавляет тестовые платежи и сообщения DLQ.
После проверки сервисы остаются работать. Остановка: docker compose stop
HELP
  exit 0
fi
if [[ $# -ne 0 ]]; then
  printf 'Неизвестные аргументы. Используйте ./run.sh --help\n' >&2
  exit 2
fi

command -v docker >/dev/null || { printf 'Требуется Docker.\n' >&2; exit 1; }
docker compose version >/dev/null
docker info >/dev/null

if [[ ! -f .env ]]; then
  cp .env.example .env
  printf 'Создан .env с демонстрационными настройками для локальной проверки.\n'
fi
docker compose config --quiet

RUN_ID="payment-check-$(date +%s)-$$"
CHECK_RECEIVER="$RUN_ID-receiver"
CHECK_CLIENT="$RUN_ID-client"
BROKER_STOPPED=0
RECEIVER_STARTED=0
CLIENT_STARTED=0

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  if [[ $BROKER_STOPPED == 1 ]]; then
    printf '\nВосстанавливаю RabbitMQ после прерванной проверки...\n' >&2
    docker compose start rabbitmq || exit_code=1
  fi
  if [[ $CLIENT_STARTED == 1 ]]; then
    docker stop --time 2 "$CHECK_CLIENT" >/dev/null 2>&1 || true
  fi
  if [[ $RECEIVER_STARTED == 1 ]]; then
    docker stop --time 5 "$CHECK_RECEIVER" >/dev/null 2>&1 || true
  fi
  if [[ $exit_code -ne 0 ]]; then
    printf '\nПроверка не завершилась успешно (код %s).\n' "$exit_code" >&2
    printf 'Диагностика: docker compose ps -a\n' >&2
    printf 'Логи: docker compose logs --tail=100 api consumer outbox-publisher\n' >&2
  fi
  exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf '\n[1/6] Сборка общего образа\n'
docker compose build api

printf '\n[2/6] Запуск инфраструктуры, миграций и приложения\n'
docker compose up -d --no-build --wait --wait-timeout 120

printf '\n[3/6] Ruff и автотесты\n'
CLIENT_STARTED=1
docker compose run --rm --no-deps -T --name "$CHECK_CLIENT" \
  -v "$PROJECT_DIR:/source:ro" api sh -c \
  'python -m ruff check --no-cache /source && python -m ruff format --check --no-cache /source && python -m pytest -q -p no:cacheprovider /source/tests'
CLIENT_STARTED=0

printf '\n[4/6] Получатель webhook и интеграционные проверки\n'
RECEIVER_STARTED=1
docker compose run --rm --no-deps -d --name "$CHECK_RECEIVER" \
  -e PYTHONPATH=/app -v "$PROJECT_DIR/scripts:/checks:ro" \
  api python -u /checks/check_docker.py receiver

check() {
  CLIENT_STARTED=1
  docker compose run --rm --no-deps -T --name "$CHECK_CLIENT" \
    -e PYTHONPATH=/app -e "CHECK_RECEIVER=$CHECK_RECEIVER" -e "CHECK_RUN_ID=$RUN_ID" \
    -v "$PROJECT_DIR/scripts:/checks:ro" \
    api python -u /checks/check_docker.py "$1"
  CLIENT_STARTED=0
}

check payments

printf '\n[5/6] Проверка сохранения Outbox при остановленном RabbitMQ\n'
BROKER_STOPPED=1
docker compose stop rabbitmq
check recovery-before

printf '\n[6/6] Проверка автоматического восстановления\n'
docker compose start rabbitmq
check recovery-after
BROKER_STOPPED=0

docker compose ps -a
printf '\nВсе проверки прошли. Сервисы приложения оставлены работающими.\n'
printf 'Адрес API: '
docker compose port api 8000
printf 'Swagger: откройте /docs на порту API.\n'
printf 'Тестовые платежи и сообщения DLQ сохранены. Остановка: docker compose stop\n'
