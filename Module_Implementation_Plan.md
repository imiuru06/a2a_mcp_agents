# A2A와 MCP 기반 자동차 정비 서비스 MSA 구현 세부 계획

## 1. 경계(Gateway) 계층 구현 세부 계획

### 1.1 Event Gateway

#### 핵심 모듈
- **EventReceiver**: 외부 이벤트 수신 및 검증
- **EventTransformer**: 이벤트 형식 변환 및 정규화
- **EventRouter**: 이벤트 유형에 따른 라우팅 로직
- **EventTracker**: 이벤트 처리 상태 추적 및 관리

#### 주요 API 엔드포인트
- `POST /api/v1/events`: 외부 시스템에서 이벤트 수신
- `GET /api/v1/events/{event_id}`: 이벤트 상태 조회
- `POST /api/v1/events/{event_id}/cancel`: 이벤트 처리 취소 요청

#### 구현 우선순위
1. 기본 이벤트 수신 및 검증 로직
2. 이벤트 라우팅 메커니즘
3. 이벤트 상태 추적 시스템
4. 재시도 및 장애 처리 로직

### 1.2 Chat Gateway

#### 핵심 모듈
- **WebSocketManager**: WebSocket 연결 관리
- **MessageProcessor**: 메시지 분류 및 전처리
- **MessageRouter**: 메시지 라우팅 로직
- **StatePublisher**: 상태 업데이트 발행 및 관리

#### 주요 API 엔드포인트
- `WebSocket /ws/chat/{user_id}`: 사용자 채팅 연결
- `WebSocket /ws/status/{task_id}`: 작업 상태 업데이트 연결
- `POST /api/v1/messages`: REST를 통한 메시지 전송

#### 구현 우선순위
1. WebSocket 서버 설정
2. 메시지 처리 및 라우팅 로직
3. 상태 업데이트 기능
4. 인증 및 권한 관리

## 2. 애플리케이션 계층 구현 세부 계획

### 2.1 Sub-Agent 공통 프레임워크

#### 핵심 모듈
- **AgentBase**: 모든 Sub-Agent의 기본 클래스
- **LLMConnector**: LLM 서비스 연결 및 요청 처리
- **MCPClient**: MCP 서버와 통신하는 클라이언트
- **A2AProtocol**: A2A 프로토콜 구현 및 통신 로직

#### 주요 API 엔드포인트
- `POST /api/v1/agents/{agent_id}/tasks`: 새 작업 할당
- `GET /api/v1/agents/{agent_id}/status`: 에이전트 상태 조회
- `POST /api/v1/agents/{agent_id}/communicate`: 다른 에이전트와 통신

### 2.2 ShopManagerAgent

#### 핵심 모듈
- **CustomerRequestHandler**: 고객 요청 접수 및 처리
- **DiagnosisEngine**: 차량 문제 진단 로직
- **TaskAssigner**: 작업 할당 및 조정
- **CustomerCommunicator**: 고객 소통 관리

#### 주요 API 엔드포인트
- `POST /api/v1/shop-manager/diagnose`: 차량 진단 요청
- `POST /api/v1/shop-manager/assign`: 작업 할당 요청
- `GET /api/v1/shop-manager/tasks/{task_id}`: 작업 상태 조회

### 2.3 MechanicAgent

#### 핵심 모듈
- **DiagnosticScanner**: 차량 스캔 및 오류 코드 분석
- **RepairProcedureManager**: 수리 절차 관리
- **ToolController**: 정비 도구 제어 인터페이스
- **RepairReporter**: 수리 과정 및 결과 보고

#### 주요 API 엔드포인트
- `POST /api/v1/mechanic/scan`: 차량 스캔 요청
- `POST /api/v1/mechanic/repair`: 수리 작업 시작 요청
- `GET /api/v1/mechanic/procedures/{error_code}`: 수리 절차 조회

### 2.4 PartsSupplierAgent

#### 핵심 모듈
- **InventoryManager**: 부품 재고 관리
- **PriceCalculator**: 가격 계산 및 견적 제공
- **OrderProcessor**: 주문 처리 및 추적
- **SupplierConnector**: 외부 공급업체 연동

#### 주요 API 엔드포인트
- `GET /api/v1/parts/inventory/{part_number}`: 부품 재고 확인
- `POST /api/v1/parts/orders`: 새 부품 주문 생성
- `GET /api/v1/parts/orders/{order_id}`: 주문 상태 조회

### 2.5 Supervisor

#### 핵심 모듈
- **TaskAggregator**: 작업 정보 집계
- **StatusMonitor**: Sub-Agent 상태 모니터링
- **DecisionEngine**: 복합 의사결정 로직
- **UserResponseGenerator**: 사용자 응답 생성
- **EscalationHandler**: 문제 에스컬레이션 처리

#### 주요 API 엔드포인트
- `GET /api/v1/supervisor/dashboard`: 전체 상태 대시보드 데이터
- `POST /api/v1/supervisor/decisions/{task_id}`: 의사결정 요청
- `POST /api/v1/supervisor/escalate`: 문제 에스컬레이션 요청

## 3. 플랫폼 계층 구현 세부 계획

### 3.1 MCP Server

#### 핵심 모듈
- **ToolExecutor**: 도구 실행 및 결과 처리
- **ContextManager**: 실행 컨텍스트 관리
- **CancellationHandler**: 작업 취소 처리
- **ParallelExecutionManager**: 병렬 실행 관리

#### 주요 API 엔드포인트
- `POST /api/v1/mcp/tools/{tool_name}/execute`: 도구 실행 요청
- `GET /api/v1/mcp/executions/{execution_id}`: 실행 상태 조회
- `POST /api/v1/mcp/executions/{execution_id}/cancel`: 실행 취소 요청

### 3.2 Tool Registry

#### 핵심 모듈
- **ToolRegistrar**: 도구 등록 및 관리
- **MetadataManager**: 도구 메타데이터 관리
- **AccessController**: 도구 접근 제어
- **ContainerManager**: 도구 컨테이너 관리

#### 주요 API 엔드포인트
- `POST /api/v1/tools`: 새 도구 등록
- `GET /api/v1/tools/{tool_id}`: 도구 정보 조회
- `GET /api/v1/tools/search`: 도구 검색 엔드포인트

## 4. 데이터 모델

### 4.1 공통 데이터 모델

#### Agent
```python
class Agent:
    agent_id: str
    name: str
    description: str
    skills: List[str]
    status: AgentStatus
    created_at: datetime
    updated_at: datetime
```

#### Task
```python
class Task:
    task_id: str
    title: str
    description: str
    status: TaskStatus
    priority: int
    created_by: str
    assigned_to: Optional[str]
    created_at: datetime
    updated_at: datetime
    context: Dict[str, Any]
    history: List[TaskEvent]
```

#### MCPTool
```python
class MCPTool:
    tool_id: str
    name: str
    description: str
    version: str
    parameters_schema: Dict[str, Any]
    return_schema: Dict[str, Any]
    container_image: Optional[str]
    access_level: AccessLevel
    created_at: datetime
    updated_at: datetime
```

### 4.2 서비스별 데이터 모델

#### Event (Event Gateway)
```python
class Event:
    event_id: str
    source: str
    event_type: str
    payload: Dict[str, Any]
    status: EventStatus
    routing_info: Dict[str, Any]
    received_at: datetime
    processed_at: Optional[datetime]
```

#### ChatMessage (Chat Gateway)
```python
class ChatMessage:
    message_id: str
    user_id: str
    content: str
    content_type: MessageType
    related_task_id: Optional[str]
    timestamp: datetime
    metadata: Dict[str, Any]
```

#### VehicleDiagnosis (MechanicAgent)
```python
class VehicleDiagnosis:
    diagnosis_id: str
    vehicle_id: str
    error_codes: List[str]
    descriptions: Dict[str, str]
    recommended_procedures: List[str]
    scan_time: datetime
    mechanic_id: str
```

#### Part (PartsSupplierAgent)
```python
class Part:
    part_id: str
    part_number: str
    name: str
    description: str
    compatible_vehicles: List[str]
    price: float
    stock: int
    location: str
    supplier_info: Dict[str, Any]
```

## 5. 서비스 간 통신

### 5.1 동기 통신

#### REST API
- 표준 HTTP 메서드 (GET, POST, PUT, DELETE)
- JSON 요청/응답 형식
- JWT 기반 인증
- 버전 관리 (`/api/v1/...`)

#### gRPC
- 고성능 내부 서비스 통신용
- 프로토콜 버퍼 정의
- 양방향 스트리밍 지원
- 서비스 디스커버리 통합

### 5.2 비동기 통신

#### Kafka 이벤트
- 주요 이벤트 토픽:
  - `agent.tasks` - 작업 관련 이벤트
  - `agent.communications` - 에이전트 간 통신
  - `system.monitoring` - 시스템 모니터링 이벤트
  - `user.interactions` - 사용자 상호작용 이벤트

#### 메시지 형식
```json
{
  "event_id": "uuid",
  "event_type": "task.created",
  "source": "shop_manager_service",
  "timestamp": "2023-10-25T08:15:30Z",
  "payload": {},
  "metadata": {}
}
```

## 6. 구현 로드맵

### 6.1 Phase 1: 핵심 인프라 및 프레임워크 (2개월)
- Kubernetes 클러스터 설정
- 서비스 메시 구성
- CI/CD 파이프라인
- 기본 모니터링 시스템
- Sub-Agent 공통 프레임워크
- MCP Server 기본 기능

### 6.2 Phase 2: 핵심 서비스 구현 (3개월)
- Event Gateway MVP
- Chat Gateway MVP
- ShopManagerAgent 기본 기능
- MechanicAgent 기본 기능
- PartsSupplierAgent 기본 기능
- Supervisor 기본 기능

### 6.3 Phase 3: 기능 확장 및 통합 (2개월)
- 서비스 간 통합
- 고급 LLM 통합
- 외부 시스템 연동
- UI/UX 개선
- 성능 최적화

### 6.4 Phase 4: 운영 준비 및 출시 (1개월)
- 부하 테스트
- 보안 점검
- 모니터링 및 알림 설정
- 사용자 문서 작성
- 베타 테스트 및 피드백 수집 