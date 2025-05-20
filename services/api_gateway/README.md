# API Gateway

MSA 아키텍처에서 모든 서비스의 단일 진입점 역할을 하는 API Gateway입니다.

## 주요 기능

- 요청 라우팅 - 적절한 마이크로서비스로 요청 전달
- 인증 - API 키 기반 인증
- 서비스 디스커버리 - 서비스 레지스트리를 통한 서비스 조회
- 응답 캐싱 - 서비스 응답 캐싱
- 오류 처리 - 통합된 오류 처리

## 환경 변수

- `SERVICE_REGISTRY_URL` - 서비스 레지스트리 URL (기본값: http://service-registry:8007/services)
- `API_KEYS` - 콤마로 구분된 유효한 API 키 목록 (기본값: test_key_1,test_key_2)

## 라우트 구성

API Gateway는 다음과 같은 라우트를 서비스에 매핑합니다:

- `/chat/*` → `chat-gateway` 서비스
- `/events/*` → `event-gateway` 서비스
- `/supervisor/*` → `supervisor` 서비스
- `/tools/*` → `tool-registry` 서비스
- `/agents/*` → `agent-card-registry` 서비스

## 인증

모든 API 요청은 HTTP 헤더에 유효한 API 키를 포함해야 합니다:

```
x-api-key: YOUR_API_KEY
```

## 서비스 디스커버리

API Gateway는 Service Registry를 사용하여 서비스 위치를 동적으로 조회합니다. 서비스 URL은 60초 동안 캐싱됩니다.

## 오류 코드

- `401` - 인증 실패
- `404` - 라우트를 찾을 수 없음
- `503` - 대상 서비스를 찾을 수 없음
- `500` - 내부 서버 오류

## 실행 방법

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

## 의존성

- FastAPI - API 서버
- HTTPX - 비동기 HTTP 클라이언트
- Service Registry - 서비스 디스커버리 