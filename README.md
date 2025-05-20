# A2A-MCP 기반 자동차 정비 서비스 MSA 시스템

A2A(Agent2Agent)와 MCP(Model Context Protocol) 프로토콜을 구현한 자동차 정비 서비스 시스템의 MSA(Microservice Architecture) 구현입니다.

## 시스템 아키텍처

이 시스템은 다음과 같은 계층으로 구성되어 있습니다:

### 1. 경계(Gateway) 계층
- **Event Gateway**: 모니터링 시스템의 이벤트 수신 및 라우팅
- **Chat Gateway**: 사용자 채팅/인터럽트/상태 메시지 처리

### 2. 애플리케이션 계층
- **Sub-Agent**:
  - **ShopManagerAgent**: 고객 요청 처리, 진단, 작업 할당
  - **MechanicAgent**: 차량 진단, 수리 수행
  - **PartsSupplierAgent**: 부품 재고 관리, 주문 처리
- **Supervisor**: 에이전트 활동 모니터링, 작업 진행 상황 집계

### 3. 플랫폼 계층
- **MCP Server**: 도구 실행 프록시, 컨텍스트 관리
- **Tool Registry**: 도구 메타데이터 관리

### 4. 인프라 계층
- **PostgreSQL**: 영구 데이터 저장
- **Redis**: 캐시 및 세션 관리
- **Kafka**: 비동기 메시징
- **Prometheus/Grafana**: 모니터링 및 시각화

## 주요 기능

- **이벤트 기반 아키텍처**: 외부 모니터링 시스템의 이벤트를 수신하여 적절한 에이전트로 라우팅
- **에이전트 간 협업(A2A)**: 각 에이전트는 특정 도메인에 특화되어 있으며, A2A 프로토콜을 통해 협업
- **도구 실행(MCP)**: MCP 프로토콜을 통한 외부 도구 호출 및 컨텍스트 관리
- **실시간 상호작용**: WebSocket을 통한 실시간 채팅 및 상태 업데이트

## 시작하기

### 사전 요구 사항

- Docker 및 Docker Compose
- Python 3.10 이상

### 설치 및 실행

1. 저장소 클론
   ```bash
   git clone https://github.com/yourusername/a2a_mcp_agents.git
   cd a2a_mcp_agents
   ```

2. Docker Compose로 서비스 실행
   ```bash
   docker-compose up -d
   ```

3. 서비스 접근
   - 프론트엔드: http://localhost:8080
   - Event Gateway: http://localhost:8010
   - MCP Server: http://localhost:8000
   - Grafana 대시보드: http://localhost:3000 (사용자: admin, 비밀번호: admin)

## 개발

### 프로젝트 구조

```
.
├── docker/                   # Dockerfile 및 docker-compose 설정
├── msa_agent_framework/      # MSA 프레임워크 코드
│   ├── agent_base.py         # 에이전트 기본 클래스
│   ├── event_gateway/        # Event Gateway 서비스
│   ├── chat_gateway/         # Chat Gateway 서비스
│   ├── mcp_server/           # MCP 서버 서비스
│   ├── shop_manager/         # Shop Manager 에이전트
│   ├── mechanic/             # Mechanic 에이전트
│   ├── parts_supplier/       # Parts Supplier 에이전트
│   └── supervisor/           # Supervisor 서비스
├── docker-compose.yml        # Docker Compose 설정
├── requirements.txt          # Python 의존성
└── README.md                 # 프로젝트 문서
```

### 새 에이전트 구현

1. `msa_agent_framework/agent_base.py`의 `AgentBase` 클래스를 상속
2. `process_event`와 `process_task` 메서드 구현
3. 도커파일 및 docker-compose 설정 추가

### 새 도구 구현

1. `msa_agent_framework/mcp_server/app.py` 파일에 도구 정의 추가
2. 도구 구현 함수 작성 및 등록

## 시스템 핵심 시나리오

### 시나리오 1: 모니터링 트리거에 의한 자동 대응

1. Event Gateway가 외부 모니터링 시스템에서 이벤트 수신
2. 이벤트 유형에 따라 적절한 Sub-Agent로 라우팅
3. Sub-Agent가 이벤트 처리 및 MCP를 통한 도구 호출
4. 처리 상태 및 결과를 Supervisor에게 보고
5. Supervisor가 전체 상황을 평가하고 사용자에게 알림

### 시나리오 2: 사용자 채팅/인터럽트를 통한 에이전트 상호작용

1. Chat Gateway가 사용자 메시지 수신
2. 메시지 유형 및 컨텍스트에 따라 Supervisor 또는 특정 Sub-Agent로 라우팅
3. Sub-Agent 또는 Supervisor가 응답 생성
4. Chat Gateway를 통해 사용자에게 응답 전송

## 기여하기

1. 이슈 또는 기능 요청 생성
2. 포크 및 브랜치 생성
3. 코드 변경 및 테스트
4. Pull Request 생성

## 라이선스

이 프로젝트는 MIT 라이선스 하에 있습니다 - 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요. 