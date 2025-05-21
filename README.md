# A2A와 MCP 프로토콜 기반 자동차 정비 서비스

## 프로젝트 개요

이 프로젝트는 A2A(Agent-to-Agent) 프로토콜과 MCP(Model Context Protocol) 기반의 자동차 정비 서비스를 위한 마이크로서비스 아키텍처(MSA)를 구현합니다. 사용자가 차량 문제에 대해 질문하면 정비 전문 에이전트가 진단 및 해결책을 제공합니다.

## 시스템 아키텍처

시스템은 다음과 같은 주요 컴포넌트로 구성되어 있습니다:

### 1. 경계(Gateway) 계층

#### 1.1 Event Gateway
- **목적**: 모니터링 시스템의 이벤트를 수신하여 Sub-Agent로 전달
- **구현 상태**: 기본 구조 구현 완료
- **주요 기능**:
  - 외부 모니터링 시스템의 이벤트 수신
  - 이벤트 필터링 및 변환
  - 적절한 Sub-Agent로 이벤트 라우팅

#### 1.2 Chat Gateway
- **목적**: 사용자 채팅/인터럽트/상태 메시지 처리 및 라우팅
- **구현 상태**: 기본 기능 구현 완료
- **주요 기능**:
  - WebSocket 연결 관리
  - 사용자 메시지 수신 및 변환
  - 메시지를 적절한 Sub-Agent 또는 Supervisor로 라우팅

### 2. 애플리케이션 계층

#### 2.1 Sub-Agent
- **목적**: 이벤트 판단, LLM 연동, MCP 도구 호출, A2A 보고
- **구현 상태**: 기본 프레임워크 구현, 도메인별 에이전트 개발 중
- **세부 Sub-Agent 구성**:
  - **ShopManagerAgent**: 고객 요청 처리, 진단, 작업 할당
  - **MechanicAgent**: 차량 진단, 수리 수행
  - **PartsSupplierAgent**: 부품 재고 관리, 주문 처리

#### 2.2 Supervisor
- **목적**: A2A 보고 수집, 상태 집계, 추가 의사결정, 사용자 응답
- **구현 상태**: 기본 기능 구현 완료
- **주요 기능**:
  - Sub-Agent 활동 모니터링
  - 작업 진행 상황 집계
  - 사용자 응답 생성 및 관리

### 3. 플랫폼 계층

#### 3.1 MCP Server
- **목적**: 도구 실행 프록시, 컨텍스트 관리, 취소 기능
- **구현 상태**: 기본 기능 구현 완료
- **주요 기능**:
  - MCP 도구 호출 관리 및 실행
  - 컨텍스트 및 상태 관리

#### 3.2 Tool Registry
- **목적**: 도구 메타데이터 관리, 컨테이너 이미지 관리
- **구현 상태**: 기본 구조 구현 완료
- **주요 기능**:
  - 도구 등록 및 메타데이터 관리
  - 접근 제어

### 4. 프론트엔드 계층

#### 4.1 Frontend (Chainlit)
- **목적**: 사용자 인터페이스 제공
- **구현 상태**: 기본 기능 구현 완료 (Chainlit 2.5.5 버전 호환성 최적화)
- **주요 기능**:
  - 채팅 기반 인터페이스
  - 파일 업로드 처리(이미지, 문서)
  - 대시보드 및 통계 데이터 시각화
  - 메시지 스트리밍 처리

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

## 현재 구현 상태

### 구현된 기능

1. **기본 인프라**:
   - 마이크로서비스 아키텍처 구조
   - Docker 기반 컨테이너화
   - 서비스 간 통신 프레임워크

2. **채팅 인터페이스**:
   - Chainlit 기반 웹 인터페이스
   - 대화형 상호작용
   - 파일 업로드 및 처리
   - 메시지 스트리밍 (토큰 단위 응답)

3. **코어 서비스**:
   - API 게이트웨이를 통한 서비스 라우팅
   - 에이전트 등록 및 관리
   - 도구 실행 및 결과 처리

### 진행 중인 작업

1. **에이전트 협업**:
   - A2A 프로토콜 구현 완성
   - 도메인별 에이전트 지능 강화

2. **도구 확장**:
   - 자동차 정비 도메인 도구 추가
   - 진단 및 문제 해결 도구 개발

3. **시스템 안정성**:
   - 서비스 간 통신 안정화
   - 오류 처리 및 복구 메커니즘 개선

## 설치 및 실행 방법

### 사전 요구사항

- Docker 및 Docker Compose
- Python 3.10 이상
- Git

### 설치 단계

1. 리포지토리 클론:
```bash
git clone https://github.com/your-organization/a2a_mcp_agents.git
cd a2a_mcp_agents
```

2. Docker 컨테이너 빌드 및 실행:
```bash
docker-compose up --build
```

3. 프론트엔드 접속:
   웹 브라우저에서 `http://localhost:8501` 접속

## 주요 시스템 접근 포인트

- **프론트엔드**: `http://localhost:8501`
- **API 게이트웨이**: `http://localhost:8000`
- **Chat 게이트웨이**: `http://localhost:8002`
- **Event 게이트웨이**: `http://localhost:8001`
- **Supervisor**: `http://localhost:8003`
- **MCP 서버**: `http://localhost:8004`
- **Tool 레지스트리**: `http://localhost:8005`

## 프로젝트 폴더 구조

```
a2a_mcp_agents/
├── services/
│   ├── frontend/              # Chainlit 기반 프론트엔드
│   ├── api_gateway/           # API 게이트웨이 서비스
│   ├── chat_gateway/          # 채팅 게이트웨이 서비스
│   ├── event_gateway/         # 이벤트 게이트웨이 서비스
│   ├── supervisor/            # 수퍼바이저 서비스
│   ├── sub_agent/             # 서브 에이전트 서비스
│   ├── mcp_server/            # MCP 서버 서비스
│   ├── tool_registry/         # 도구 레지스트리 서비스
│   └── llm_registry/          # LLM 레지스트리 서비스
├── architecture/              # 아키텍처 다이어그램 및 문서
├── docker-compose.yml         # 도커 컴포즈 설정
└── README.md                  # 프로젝트 문서
```

## 기여 방법

1. 이슈 등록 또는 기존 이슈 선택
2. 브랜치 생성: `git checkout -b feature/your-feature-name`
3. 변경사항 커밋: `git commit -m "Add feature"`
4. 푸시: `git push origin feature/your-feature-name`
5. Pull Request 생성

## 라이센스

이 프로젝트는 MIT 라이센스 하에 배포됩니다. 