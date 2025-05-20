# 서비스 레지스트리 (Service Registry)

MSA 아키텍처에서 서비스 디스커버리를 위한 중앙 레지스트리입니다.

## 주요 기능

- 서비스 등록 및 해제
- 헬스체크 및 서비스 상태 관리
- 서비스 디스커버리 (이름으로 서비스 찾기)
- 하트비트 메커니즘으로 가용성 추적

## API 엔드포인트

- `GET /health` - 헬스체크
- `POST /services` - 서비스 등록
- `PUT /services/{service_id}/heartbeat` - 서비스 하트비트 업데이트
- `GET /services` - 서비스 목록 조회
- `GET /services/{service_id}` - 특정 서비스 조회
- `DELETE /services/{service_id}` - 서비스 등록 해제
- `PUT /services/{service_id}` - 서비스 정보 업데이트
- `GET /services/discovery/{service_name}` - 서비스 디스커버리

## 환경 변수

- `REDIS_HOST` - Redis 호스트 (기본값: redis)
- `REDIS_PORT` - Redis 포트 (기본값: 6379)
- `REDIS_DB` - Redis DB 번호 (기본값: 0)
- `SERVICE_TTL` - 서비스 TTL (기본값: 60초)

## 사용 예시

### 서비스 등록
```bash
curl -X POST "http://localhost:8007/services" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-service",
    "url": "http://my-service:8123",
    "health_check_url": "http://my-service:8123/health",
    "metadata": {
      "version": "1.0",
      "description": "My awesome service"
    }
  }'
```

### 서비스 디스커버리
```bash
curl -X GET "http://localhost:8007/services/discovery/my-service"
```

## 실행 방법

```bash
uvicorn app:app --host 0.0.0.0 --port 8007
```

## 의존성

- Redis - 서비스 정보 저장 및 TTL 관리
- FastAPI - API 서버
- Uvicorn - ASGI 서버 