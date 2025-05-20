#!/usr/bin/env python3
"""
A2A와 MCP 프로토콜 통합 아키텍처 구성 요소 정의

이 모듈은 전체 MSA 아키텍처의 각 계층과 컴포넌트를 정의하며,
각 컴포넌트의 책임과 상호작용을 설명합니다.
"""

from enum import Enum
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field


class ArchitectureLayer(str, Enum):
    """아키텍처 계층 정의"""
    GATEWAY = "gateway"
    APPLICATION = "application"
    PLATFORM = "platform"
    OPTIONAL = "optional"


class ComponentType(str, Enum):
    """컴포넌트 유형 정의"""
    EVENT_GATEWAY = "event_gateway"
    CHAT_GATEWAY = "chat_gateway"
    SUB_AGENT = "sub_agent"
    SUPERVISOR = "supervisor"
    MCP_SERVER = "mcp_server"
    TOOL_REGISTRY = "tool_registry"
    OBSERVABILITY = "observability"


@dataclass
class SubModule:
    """하위 모듈 정의"""
    name: str
    description: str
    responsibilities: List[str]
    technologies: List[str] = field(default_factory=list)


@dataclass
class Component:
    """아키텍처 컴포넌트 정의"""
    component_type: ComponentType
    layer: ArchitectureLayer
    name: str
    description: str
    responsibilities: List[str]
    protocols: List[str]
    features: List[str]
    sub_modules: List[SubModule] = field(default_factory=list)


# 경계(Gateway) 계층 컴포넌트 정의
EVENT_GATEWAY = Component(
    component_type=ComponentType.EVENT_GATEWAY,
    layer=ArchitectureLayer.GATEWAY,
    name="Event Gateway",
    description="모니터링 시스템의 HTTP POST 트리거 수신 후 Sub-Agent로 포워딩",
    responsibilities=[
        "모니터링 시스템 POST 수신",
        "Sub-Agent로 포워딩"
    ],
    protocols=["REST"],
    features=["재시도/속도제한", "HA 로드밸런싱"],
    sub_modules=[
        SubModule(
            name="HTTP POST 핸들러",
            description="모니터링 시스템으로부터 이벤트를 수신하는 HTTP 엔드포인트",
            responsibilities=[
                "JSON 이벤트 페이로드 검증",
                "이벤트 유형에 따른 라우팅",
                "응답 생성 및 반환"
            ],
            technologies=["FastAPI", "Pydantic"]
        ),
        SubModule(
            name="재시도/속도제한 미들웨어",
            description="요청 처리의 안정성과 시스템 보호를 위한 미들웨어",
            responsibilities=[
                "지수 백오프 재시도 로직",
                "IP/클라이언트 기반 속도 제한",
                "과부하 방지 회로 차단기"
            ],
            technologies=["Redis", "Token Bucket Algorithm"]
        ),
        SubModule(
            name="HA 로드밸런싱 설정",
            description="고가용성 및 부하 분산을 위한 인프라 설정",
            responsibilities=[
                "다중 인스턴스 배포",
                "상태 확인 및 장애 조치",
                "요청 분산"
            ],
            technologies=["Kubernetes Ingress", "HPA", "Service Mesh"]
        )
    ]
)

CHAT_GATEWAY = Component(
    component_type=ComponentType.CHAT_GATEWAY,
    layer=ArchitectureLayer.GATEWAY,
    name="Chat Gateway",
    description="사용자 챗/인터럽트 메시지를 목표 Agent로 라우팅",
    responsibilities=[
        "사용자 chat/interrupt/status 메시지 처리",
        "대상 Agent 라우팅"
    ],
    protocols=["HTTP", "WebSocket", "SSE"],
    features=["라우팅 테이블 캐시", "인증·세션 관리"],
    sub_modules=[
        SubModule(
            name="REST/WS/SSE 엔드포인트",
            description="다양한 프로토콜을 통한 클라이언트 통신 처리",
            responsibilities=[
                "HTTP REST API 엔드포인트",
                "WebSocket 연결 관리",
                "Server-Sent Events 스트림"
            ],
            technologies=["FastAPI", "WebSockets", "SSE"]
        ),
        SubModule(
            name="라우팅 테이블 캐시",
            description="에이전트 ID와 엔드포인트 매핑 관리",
            responsibilities=[
                "에이전트 디렉토리 캐싱",
                "TTL 기반 캐시 갱신",
                "서비스 디스커버리 연동"
            ],
            technologies=["Redis", "Service Discovery"]
        ),
        SubModule(
            name="인증·세션 관리",
            description="사용자 인증 및 세션 상태 관리",
            responsibilities=[
                "JWT 토큰 검증",
                "세션 상태 유지",
                "권한 검사"
            ],
            technologies=["JWT", "OAuth2", "Redis Session Store"]
        )
    ]
)

# 애플리케이션 계층 컴포넌트 정의
SUB_AGENT = Component(
    component_type=ComponentType.SUB_AGENT,
    layer=ArchitectureLayer.APPLICATION,
    name="Sub-Agent",
    description="이벤트 1차 판단 및 복잡 로직은 MCP 호출, 결과를 Supervisor에 A2A 보고",
    responsibilities=[
        "1차 이벤트 판단",
        "복잡 로직은 MCP 호출",
        "결과를 Supervisor에 A2A 보고"
    ],
    protocols=["REST API", "A2A (JSON-RPC)"],
    features=["내장 Rule 엔진", "LLM 연동", "Tool-Client (MCP RPC)"],
    sub_modules=[
        SubModule(
            name="이벤트 Rule 엔진",
            description="이벤트를 평가하고 판단하는 내장 규칙 엔진",
            responsibilities=[
                "내장 룰 DSL 설계",
                "룰 평가 모듈",
                "판단 결과 생성"
            ],
            technologies=["Rules DSL", "Condition Evaluator"]
        ),
        SubModule(
            name="LLM 연동",
            description="복잡한 이벤트 분석을 위한 LLM 통합",
            responsibilities=[
                "LLM API 클라이언트",
                "프롬프트 템플릿 관리",
                "응답 파싱 및 처리"
            ],
            technologies=["OpenAI API", "Anthropic API", "Prompt Engineering"]
        ),
        SubModule(
            name="Tool-Client (MCP RPC)",
            description="MCP 프로토콜을 통한 외부 도구 호출",
            responsibilities=[
                "MCP JSON-RPC 클라이언트",
                "호출/취소/상태 조회 API",
                "결과 처리"
            ],
            technologies=["JSON-RPC", "HTTP Client", "Async IO"]
        ),
        SubModule(
            name="A2A 클라이언트",
            description="Supervisor와의 A2A 통신 처리",
            responsibilities=[
                "Supervisor REST 호출",
                "메시지 중복·순서 보장",
                "상태 보고"
            ],
            technologies=["A2A Protocol", "REST Client"]
        )
    ]
)

SUPERVISOR = Component(
    component_type=ComponentType.SUPERVISOR,
    layer=ArchitectureLayer.APPLICATION,
    name="Supervisor",
    description="Sub-Agent 보고 수집 및 상태 집계, 추가 의사결정 및 사용자 챗 응답",
    responsibilities=[
        "Sub-Agent 보고 집계",
        "추가 Tool/Agent 호출",
        "채팅 인터페이스 담당"
    ],
    protocols=["REST API", "A2A"],
    features=["A2A 리포트 수집", "상태 집계 엔진", "추가 의사결정 모듈"],
    sub_modules=[
        SubModule(
            name="A2A 리포트 수집",
            description="Sub-Agent로부터 보고 수집 및 관리",
            responsibilities=[
                "Sub-Agent → 보고 수신 API",
                "상태 DB 관리",
                "보고 검증"
            ],
            technologies=["FastAPI", "Redis/In-memory DB"]
        ),
        SubModule(
            name="상태 집계 엔진",
            description="여러 보고를 집계하여 전체 상태 판단",
            responsibilities=[
                "보고 집계 로직",
                "상태 전이 관리",
                "우선순위 평가"
            ],
            technologies=["State Machine", "Event Sourcing"]
        ),
        SubModule(
            name="추가 의사결정 모듈",
            description="집계된 정보를 바탕으로 추가 조치 결정",
            responsibilities=[
                "추가 Tool/Agent 호출 룰",
                "조치 계획 수립",
                "결과 평가"
            ],
            technologies=["Decision Trees", "Rule Engine"]
        ),
        SubModule(
            name="사용자 챗 응답기",
            description="사용자와의 채팅 인터페이스 관리",
            responsibilities=[
                "Chat Gateway 연동",
                "SSE 응답 스트리밍",
                "대화 컨텍스트 관리"
            ],
            technologies=["SSE", "Async Streams", "Context Management"]
        )
    ]
)

# 플랫폼 계층 컴포넌트 정의
MCP_SERVER = Component(
    component_type=ComponentType.MCP_SERVER,
    layer=ArchitectureLayer.PLATFORM,
    name="MCP Server",
    description="Tool 실행 및 상태 스트리밍, 실행 취소 처리",
    responsibilities=[
        "Tool 실행 및 상태 스트리밍",
        "실행 취소 처리"
    ],
    protocols=["MCP (JSON over HTTP)", "SSE/WS"],
    features=["Tool 실행 프록시", "컨텍스트 저장소", "취소 토큰 관리"],
    sub_modules=[
        SubModule(
            name="Tool 실행 프록시",
            description="외부 도구 실행 및 관리",
            responsibilities=[
                "요청 스케줄러",
                "Docker 컨테이너 런처",
                "결과 반환"
            ],
            technologies=["Docker API", "Scheduler", "Process Management"]
        ),
        SubModule(
            name="컨텍스트 저장소",
            description="도구 실행 컨텍스트 관리",
            responsibilities=[
                "실행별 컨텍스트 저장",
                "상태 추적",
                "히스토리 관리"
            ],
            technologies=["KV Store", "Database", "Context Management"]
        ),
        SubModule(
            name="취소 토큰 관리",
            description="실행 중인 작업의 취소 처리",
            responsibilities=[
                "취소 토큰 발행·전파",
                "실행 중단 처리",
                "리소스 정리"
            ],
            technologies=["Cancellation Tokens", "Signal Handling"]
        ),
        SubModule(
            name="SSE/WS 스트리밍",
            description="실행 상태의 실시간 스트리밍",
            responsibilities=[
                "SSE/WebSocket 구현",
                "진행 상태 전송",
                "로그 스트리밍"
            ],
            technologies=["SSE", "WebSockets", "Async Streams"]
        )
    ]
)

TOOL_REGISTRY = Component(
    component_type=ComponentType.TOOL_REGISTRY,
    layer=ArchitectureLayer.PLATFORM,
    name="Tool Registry",
    description="Tool 목록·버전 관리, 이미지 배포·캐싱",
    responsibilities=[
        "Tool 목록·버전 관리",
        "이미지 배포·캐싱"
    ],
    protocols=["REST/gRPC"],
    features=["메타데이터 DB", "컨테이너 이미지 레지스트리", "캐시 계층"],
    sub_modules=[
        SubModule(
            name="메타데이터 DB",
            description="도구 메타데이터 및 버전 관리",
            responsibilities=[
                "Tool schema 관리",
                "버전 호환성 추적",
                "메타데이터 CRUD API"
            ],
            technologies=["PostgreSQL", "MongoDB", "Schema Registry"]
        ),
        SubModule(
            name="컨테이너 이미지 레지스트리",
            description="도구 컨테이너 이미지 관리",
            responsibilities=[
                "CI 빌드 파이프라인",
                "이미지 태깅·푸시",
                "버전 관리"
            ],
            technologies=["Docker Registry", "CI/CD", "GitOps"]
        ),
        SubModule(
            name="캐시 계층",
            description="도구 메타데이터 및 이미지 캐싱",
            responsibilities=[
                "CDN/Redis 프론트",
                "캐시 무효화",
                "분산 캐싱"
            ],
            technologies=["Redis", "CDN", "Cache Invalidation"]
        )
    ]
)

# 옵셔널 계층 컴포넌트 정의
OBSERVABILITY = Component(
    component_type=ComponentType.OBSERVABILITY,
    layer=ArchitectureLayer.OPTIONAL,
    name="Observability",
    description="분산 추적·로그·메트릭 수집, 장애 알림",
    responsibilities=[
        "분산 추적·로그·메트릭 수집",
        "장애 알림"
    ],
    protocols=["OpenTelemetry", "Prometheus"],
    features=["OpenTelemetry Instrumentation", "로그 집계", "메트릭", "Alert 룰"],
    sub_modules=[
        SubModule(
            name="OpenTelemetry Instrumentation",
            description="분산 추적 및 텔레메트리 계측",
            responsibilities=[
                "서비스 SDK 적용",
                "스팬/컨텍스트 전파",
                "추적 데이터 수집"
            ],
            technologies=["OpenTelemetry SDK", "Context Propagation", "Jaeger/Zipkin"]
        ),
        SubModule(
            name="로그 집계",
            description="시스템 전반의 로그 수집 및 분석",
            responsibilities=[
                "Fluentd/Logstash 파이프라인",
                "로그 포맷 표준화",
                "검색 및 분석"
            ],
            technologies=["ELK Stack", "Fluentd", "Loki"]
        ),
        SubModule(
            name="Prometheus 메트릭",
            description="시스템 및 비즈니스 메트릭 수집",
            responsibilities=[
                "메트릭 익스포터",
                "Prometheus scrape 설정",
                "시계열 데이터 저장"
            ],
            technologies=["Prometheus", "Exporters", "PromQL"]
        ),
        SubModule(
            name="Alert 룰",
            description="이상 징후 감지 및 알림",
            responsibilities=[
                "Grafana 대시보드",
                "Alertmanager 룰",
                "알림 채널 연동"
            ],
            technologies=["Grafana", "Alertmanager", "PagerDuty/Slack Integration"]
        )
    ]
)

# 전체 아키텍처 구성요소 맵
ARCHITECTURE_COMPONENTS = {
    ComponentType.EVENT_GATEWAY: EVENT_GATEWAY,
    ComponentType.CHAT_GATEWAY: CHAT_GATEWAY,
    ComponentType.SUB_AGENT: SUB_AGENT,
    ComponentType.SUPERVISOR: SUPERVISOR,
    ComponentType.MCP_SERVER: MCP_SERVER,
    ComponentType.TOOL_REGISTRY: TOOL_REGISTRY,
    ComponentType.OBSERVABILITY: OBSERVABILITY
}

# 계층별 컴포넌트 맵
LAYER_COMPONENTS = {
    ArchitectureLayer.GATEWAY: [EVENT_GATEWAY, CHAT_GATEWAY],
    ArchitectureLayer.APPLICATION: [SUB_AGENT, SUPERVISOR],
    ArchitectureLayer.PLATFORM: [MCP_SERVER, TOOL_REGISTRY],
    ArchitectureLayer.OPTIONAL: [OBSERVABILITY]
}


def get_component_by_type(component_type: ComponentType) -> Optional[Component]:
    """컴포넌트 유형으로 컴포넌트 조회"""
    return ARCHITECTURE_COMPONENTS.get(component_type)


def get_components_by_layer(layer: ArchitectureLayer) -> List[Component]:
    """계층으로 컴포넌트 목록 조회"""
    return LAYER_COMPONENTS.get(layer, [])


def get_all_components() -> List[Component]:
    """모든 컴포넌트 목록 조회"""
    return list(ARCHITECTURE_COMPONENTS.values())


if __name__ == "__main__":
    # 아키텍처 구성요소 출력 예시
    print("=== A2A와 MCP 통합 MSA 아키텍처 구성요소 ===")
    
    for layer in ArchitectureLayer:
        print(f"\n## {layer.value.upper()} 계층")
        for component in get_components_by_layer(layer):
            print(f"- {component.name}: {component.description}")
            print(f"  주요 책임: {', '.join(component.responsibilities)}")
            print(f"  프로토콜: {', '.join(component.protocols)}")
            print(f"  특징: {', '.join(component.features)}") 