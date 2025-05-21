FROM python:3.10-slim

WORKDIR /app

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chainlit 설정 디렉토리 생성
RUN mkdir -p .chainlit

# 애플리케이션 코드 복사
COPY . .

# 환경 변수 설정
ENV CHAINLIT_SERVER_PORT=8000
ENV CHAINLIT_SERVER_HOST=0.0.0.0
ENV CHAINLIT_MAX_TOKENS=2000
ENV CHAINLIT_HIDE_COT=true

# 서비스 연결 설정
ENV API_GATEWAY_URL=http://api-gateway:8000
ENV CHAT_GATEWAY_URL=http://chat-gateway:8002
ENV SUPERVISOR_URL=http://supervisor:8003
ENV TOOL_REGISTRY_URL=http://tool-registry:8005
ENV EVENT_GATEWAY_URL=http://event-gateway:8001
ENV MCP_SERVER_URL=http://mcp-server:8004

# 통신 재시도 설정
ENV MAX_RETRIES=3
ENV RETRY_DELAY=1.0

# 상태 확인 스크립트 추가
COPY healthcheck.sh /healthcheck.sh
RUN chmod +x /healthcheck.sh

# 포트 노출
EXPOSE 8000

# 헬스체크 설정
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 CMD [ "/healthcheck.sh" ]

# 애플리케이션 실행
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"] 