FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    && rm -rf /var/lib/apt/lists/*

# 애플리케이션 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY . .

# 비 루트 사용자 생성
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -s /bin/bash -m appuser

# 애플리케이션 디렉토리 소유권 변경
RUN chown -R appuser:appuser /app

# 비 루트 사용자로 전환
USER appuser

# 환경 변수 설정
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    LOG_LEVEL=INFO

# 포트 노출
EXPOSE 8000

# 상태 체크 및 메트릭 포트
EXPOSE 8000

# 애플리케이션 실행
CMD ["uvicorn", "event_handler:app", "--host", "0.0.0.0", "--port", "8000"]

# 상태 체크
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1 