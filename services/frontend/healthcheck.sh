#!/bin/bash

# 기본 서비스 상태 확인
CHAINLIT_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000)

if [ "$CHAINLIT_HEALTH" -eq 200 ] || [ "$CHAINLIT_HEALTH" -eq 302 ]; then
  echo "Chainlit 서비스가 정상적으로 실행 중입니다. 상태 코드: $CHAINLIT_HEALTH"
  exit 0
else
  echo "Chainlit 서비스에 문제가 있습니다. 상태 코드: $CHAINLIT_HEALTH"
  exit 1
fi 