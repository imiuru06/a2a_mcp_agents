# Agent Card Registry (에이전트 카드 레지스트리)

MSA 아키텍처에서 에이전트의 능력과 특성을 관리하고 작업 할당을 최적화하는 서비스입니다.

## 주요 기능

- 에이전트 등록 및 관리
- 에이전트 능력(Capability) 관리
- 작업에 적합한 에이전트 추천
- 에이전트 상태 추적
- 메타데이터 기반 에이전트 필터링

## API 엔드포인트

### 에이전트 관련

- `GET /health` - 헬스체크
- `POST /agents` - 새 에이전트 등록
- `GET /agents` - 에이전트 목록 조회
- `GET /agents/{agent_id}` - 특정 에이전트 조회
- `PUT /agents/{agent_id}` - 에이전트 정보 업데이트
- `DELETE /agents/{agent_id}` - 에이전트 삭제
- `POST /agents/find` - 필요한 능력을 가진 에이전트 찾기

### 능력(Capability) 관련

- `POST /capabilities` - 새 능력 등록
- `GET /capabilities` - 능력 목록 조회
- `GET /capabilities/{capability_id}` - 특정 능력 조회
- `PUT /capabilities/{capability_id}` - 능력 정보 업데이트
- `DELETE /capabilities/{capability_id}` - 능력 삭제

## 환경 변수

- `DATABASE_URL` - PostgreSQL 연결 문자열 (기본값: postgresql://postgres:postgres@postgres:5432/agent_registry)
- `SERVICE_REGISTRY_URL` - 서비스 레지스트리 URL (기본값: http://service-registry:8007/services)
- `MESSAGE_BROKER_URL` - 메시지 브로커 URL (기본값: amqp://message-broker:5672)

## 데이터 모델

### 에이전트(Agent)

```json
{
  "id": "uuid",
  "name": "mechanic-agent",
  "description": "차량 진단 및 수리 전문 에이전트",
  "version": "1.0.0",
  "url": "http://sub-agent:8000/mechanic",
  "health_check_url": "http://sub-agent:8000/health",
  "status": "active",
  "metadata": {
    "specialty": "engine",
    "experience_level": "expert"
  },
  "capabilities": ["diagnose_engine", "repair_transmission", "order_parts"],
  "created_at": "2023-06-01T12:00:00Z",
  "updated_at": "2023-06-02T15:30:00Z"
}
```

### 능력(Capability)

```json
{
  "id": "uuid",
  "name": "diagnose_engine",
  "description": "엔진 문제 진단 능력",
  "category": "diagnosis",
  "priority": 8,
  "metadata": {
    "required_tools": ["obd_scanner", "engine_analyzer"]
  },
  "created_at": "2023-06-01T10:00:00Z",
  "agents": ["mechanic-agent", "master-technician"]
}
```

## 작업 할당 로직

에이전트 찾기 API(`POST /agents/find`)는 다음과 같은 로직으로 작업에 적합한 에이전트를 추천합니다:

1. 필수 능력(required_capabilities)을 모두 가진 에이전트 필터링
2. 선호 능력(preferred_capabilities)에 따른 점수 계산
3. 메타데이터 필터(metadata_filters)를 만족하는 에이전트 필터링
4. 점수에 따라 정렬하여 반환

## 사용 예시

### 에이전트 등록

```bash
curl -X POST "http://localhost:8006/agents" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mechanic-agent",
    "description": "차량 진단 및 수리 전문 에이전트",
    "version": "1.0.0",
    "url": "http://sub-agent:8000/mechanic",
    "health_check_url": "http://sub-agent:8000/health",
    "metadata": {
      "specialty": "engine",
      "experience_level": "expert"
    },
    "capabilities": ["diagnose_engine", "repair_transmission", "order_parts"]
  }'
```

### 특정 작업에 적합한 에이전트 찾기

```bash
curl -X POST "http://localhost:8006/agents/find" \
  -H "Content-Type: application/json" \
  -d '{
    "required_capabilities": ["diagnose_engine"],
    "preferred_capabilities": ["repair_transmission", "order_parts"],
    "metadata_filters": {
      "specialty": "engine"
    }
  }'
```

## 실행 방법

```bash
uvicorn app:app --host 0.0.0.0 --port 8006
```

## 의존성

- PostgreSQL - 에이전트 및 능력 정보 저장
- FastAPI - API 서버
- SQLAlchemy - ORM
- Service Registry - 서비스 디스커버리 