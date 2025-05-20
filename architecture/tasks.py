#!/usr/bin/env python3
"""
A2A와 MCP 프로토콜 통합 아키텍처 구현을 위한 컴포넌트별 Task 분할

이 모듈은 각 컴포넌트별로 구체적인 구현 작업을 정의합니다.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class TaskStatus(str, Enum):
    """작업 상태 정의"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class TaskPriority(str, Enum):
    """작업 우선순위 정의"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Task:
    """구현 작업 정의"""
    id: str
    name: str
    description: str
    component: str
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.NOT_STARTED
    dependencies: List[str] = field(default_factory=list)
    subtasks: List[str] = field(default_factory=list)
    estimated_hours: float = 0.0
    assignee: Optional[str] = None
    technologies: List[str] = field(default_factory=list)
    deliverables: List[str] = field(default_factory=list)


# ----- Event Gateway 컴포넌트 태스크 -----
EVENT_GATEWAY_TASKS = [
    Task(
        id="eg-001",
        name="API 설계 - /event POST 스펙 정의",
        description="모니터링 시스템에서 전송되는 이벤트를 수신하는 API 스펙 정의",
        component="Event Gateway",
        priority=TaskPriority.HIGH,
        technologies=["OpenAPI", "JSON Schema"],
        deliverables=["event_api_spec.yaml", "event_schema.json"]
    ),
    Task(
        id="eg-002",
        name="HTTP POST 핸들러 구현",
        description="이벤트 수신 및 유효성 검사 핸들러 구현",
        component="Event Gateway",
        dependencies=["eg-001"],
        technologies=["FastAPI", "Pydantic"],
        deliverables=["event_handler.py", "validation.py"]
    ),
    Task(
        id="eg-003",
        name="재시도 로직 구현",
        description="지수 백오프 기반 재시도 로직 구현",
        component="Event Gateway",
        technologies=["Exponential Backoff", "Retry Pattern"],
        deliverables=["retry_middleware.py"]
    ),
    Task(
        id="eg-004",
        name="속도 제한 미들웨어 구현",
        description="IP 및 클라이언트 기반 속도 제한 구현",
        component="Event Gateway",
        technologies=["Redis", "Token Bucket Algorithm"],
        deliverables=["rate_limiter.py"]
    ),
    Task(
        id="eg-005",
        name="Sub-Agent 포워딩 클라이언트 구현",
        description="이벤트를 Sub-Agent로 전달하는 클라이언트 구현",
        component="Event Gateway",
        dependencies=["eg-002"],
        technologies=["HTTP Client", "Async IO"],
        deliverables=["subagent_client.py"]
    ),
    Task(
        id="eg-006",
        name="Kubernetes Ingress / Service 정의",
        description="Event Gateway 서비스를 위한 Kubernetes 리소스 정의",
        component="Event Gateway",
        technologies=["Kubernetes", "YAML"],
        deliverables=["event-gateway-deployment.yaml", "event-gateway-service.yaml", "event-gateway-ingress.yaml"]
    ),
    Task(
        id="eg-007",
        name="HPA 설정 구성",
        description="CPU 및 메모리 기반 HPA(Horizontal Pod Autoscaler) 설정",
        component="Event Gateway",
        dependencies=["eg-006"],
        technologies=["Kubernetes HPA", "Metrics Server"],
        deliverables=["event-gateway-hpa.yaml"]
    ),
    Task(
        id="eg-008",
        name="단위 테스트 작성",
        description="성공/실패/재시도 경로에 대한 단위 테스트 구현",
        component="Event Gateway",
        dependencies=["eg-002", "eg-003", "eg-004", "eg-005"],
        technologies=["pytest", "unittest.mock"],
        deliverables=["test_event_handler.py", "test_retry.py", "test_rate_limiter.py"]
    ),
    Task(
        id="eg-009",
        name="부하 테스트 스크립트 작성",
        description="JMeter를 사용한 부하 테스트 스크립트 작성",
        component="Event Gateway",
        dependencies=["eg-002", "eg-003", "eg-004"],
        technologies=["JMeter", "Load Testing"],
        deliverables=["event_gateway_load_test.jmx"]
    )
]

# ----- Chat Gateway 컴포넌트 태스크 -----
CHAT_GATEWAY_TASKS = [
    Task(
        id="cg-001",
        name="Redis 스키마 설계",
        description="에이전트 ID와 엔드포인트 매핑을 위한 Redis 스키마 설계",
        component="Chat Gateway",
        technologies=["Redis", "Data Modeling"],
        deliverables=["routing_table_schema.md"]
    ),
    Task(
        id="cg-002",
        name="라우팅 테이블 캐시 구현",
        description="TTL 기반 캐시 및 Service Discovery 연동 구현",
        component="Chat Gateway",
        dependencies=["cg-001"],
        technologies=["Redis", "Service Discovery", "TTL Cache"],
        deliverables=["routing_cache.py", "service_discovery.py"]
    ),
    Task(
        id="cg-003",
        name="JWT 토큰 검증 모듈 구현",
        description="사용자 인증을 위한 JWT 토큰 검증 모듈 구현",
        component="Chat Gateway",
        technologies=["JWT", "Authentication"],
        deliverables=["auth.py", "token_validator.py"]
    ),
    Task(
        id="cg-004",
        name="WebSocket 세션 매니저 구현",
        description="WebSocket 연결 관리 및 세션 상태 유지 구현",
        component="Chat Gateway",
        technologies=["WebSockets", "Session Management"],
        deliverables=["websocket_manager.py", "session_store.py"]
    ),
    Task(
        id="cg-005",
        name="채팅 메시지 핸들러 구현",
        description="채팅 메시지를 REST/WS로 포워딩하고 SSE 스트림 연결하는 핸들러 구현",
        component="Chat Gateway",
        dependencies=["cg-002", "cg-004"],
        technologies=["FastAPI", "SSE", "WebSockets"],
        deliverables=["chat_handler.py", "sse_stream.py"]
    ),
    Task(
        id="cg-006",
        name="인터럽트 메시지 핸들러 구현",
        description="/agent/{id}/interrupt?run_id= 호출 처리 구현",
        component="Chat Gateway",
        dependencies=["cg-002"],
        technologies=["FastAPI", "HTTP Client"],
        deliverables=["interrupt_handler.py"]
    ),
    Task(
        id="cg-007",
        name="상태 메시지 핸들러 구현",
        description="/agent/{id}/status?run_id= 스트리밍 처리 구현",
        component="Chat Gateway",
        dependencies=["cg-002"],
        technologies=["FastAPI", "SSE", "Async Streams"],
        deliverables=["status_handler.py", "status_stream.py"]
    ),
    Task(
        id="cg-008",
        name="E2E 테스트 구현",
        description="Web 클라이언트 시뮬레이터를 사용한 E2E 테스트 구현",
        component="Chat Gateway",
        dependencies=["cg-005", "cg-006", "cg-007"],
        technologies=["Playwright", "E2E Testing"],
        deliverables=["chat_gateway_e2e_test.py", "web_client_simulator.py"]
    )
]

# ----- Sub-Agent 컴포넌트 태스크 -----
SUB_AGENT_TASKS = [
    Task(
        id="sa-001",
        name="내장 룰 DSL 설계",
        description="이벤트 평가를 위한 내장 룰 DSL 설계",
        component="Sub-Agent",
        priority=TaskPriority.HIGH,
        technologies=["DSL Design", "Grammar Definition"],
        deliverables=["rule_dsl_spec.md", "rule_grammar.ebnf"]
    ),
    Task(
        id="sa-002",
        name="룰 평가 모듈 구현",
        description="룰 DSL을 평가하는 모듈 구현",
        component="Sub-Agent",
        dependencies=["sa-001"],
        technologies=["Parser Combinators", "Interpreter Pattern"],
        deliverables=["rule_evaluator.py", "rule_parser.py"]
    ),
    Task(
        id="sa-003",
        name="OpenAI/타 LLM 클라이언트 래퍼 구현",
        description="다양한 LLM API를 일관된 인터페이스로 래핑하는 클라이언트 구현",
        component="Sub-Agent",
        technologies=["OpenAI API", "Anthropic API", "HTTP Client"],
        deliverables=["llm_client.py", "openai_wrapper.py", "anthropic_wrapper.py"]
    ),
    Task(
        id="sa-004",
        name="프롬프트 템플릿 매니저 구현",
        description="LLM 프롬프트 템플릿을 관리하는 매니저 구현",
        component="Sub-Agent",
        dependencies=["sa-003"],
        technologies=["Template Engine", "Jinja2"],
        deliverables=["prompt_manager.py", "templates/"]
    ),
    Task(
        id="sa-005",
        name="MCP JSON-RPC 클라이언트 구현",
        description="MCP 서버와 통신하는 JSON-RPC 클라이언트 구현",
        component="Sub-Agent",
        technologies=["JSON-RPC", "HTTP Client", "Async IO"],
        deliverables=["mcp_client.py", "json_rpc.py"]
    ),
    Task(
        id="sa-006",
        name="호출/취소/상태 조회 API 래핑",
        description="MCP 서버의 호출/취소/상태 조회 API를 래핑하는 구현",
        component="Sub-Agent",
        dependencies=["sa-005"],
        technologies=["API Client", "Error Handling"],
        deliverables=["tool_executor.py", "cancellation.py", "status_tracker.py"]
    ),
    Task(
        id="sa-007",
        name="Supervisor REST 콜러 구현",
        description="Supervisor에게 결과를 보고하는 REST 클라이언트 구현",
        component="Sub-Agent",
        technologies=["HTTP Client", "A2A Protocol"],
        deliverables=["supervisor_client.py", "a2a_reporter.py"]
    ),
    Task(
        id="sa-008",
        name="메시지 중복·순서 보장 로직 구현",
        description="A2A 통신에서 메시지 중복 제거 및 순서 보장 로직 구현",
        component="Sub-Agent",
        dependencies=["sa-007"],
        technologies=["Message Ordering", "Idempotency"],
        deliverables=["message_ordering.py", "idempotency.py"]
    ),
    Task(
        id="sa-009",
        name="Rule 엔진 유닛 테스트 작성",
        description="Rule 엔진에 대한 유닛 테스트 작성",
        component="Sub-Agent",
        dependencies=["sa-002"],
        technologies=["pytest", "unittest.mock"],
        deliverables=["test_rule_evaluator.py", "test_rule_parser.py"]
    ),
    Task(
        id="sa-010",
        name="LLM 샌드박스 통합 테스트 작성",
        description="LLM 통합을 위한 샌드박스 테스트 작성",
        component="Sub-Agent",
        dependencies=["sa-003", "sa-004"],
        technologies=["pytest", "VCR.py"],
        deliverables=["test_llm_integration.py", "fixtures/llm_responses.json"]
    )
]

# ----- Supervisor Agent 컴포넌트 태스크 -----
SUPERVISOR_TASKS = [
    Task(
        id="sv-001",
        name="Sub-Agent 보고 수신 API 구현",
        description="Sub-Agent로부터 보고를 수신하는 API 구현",
        component="Supervisor",
        technologies=["FastAPI", "A2A Protocol"],
        deliverables=["report_receiver.py", "api_routes.py"]
    ),
    Task(
        id="sv-002",
        name="상태 DB 구현",
        description="인메모리 또는 Redis 기반 상태 DB 구현",
        component="Supervisor",
        technologies=["Redis", "In-memory DB"],
        deliverables=["state_store.py", "redis_adapter.py"]
    ),
    Task(
        id="sv-003",
        name="보고 집계 로직 구현",
        description="Sub-Agent 보고를 집계하고 상태 전이를 관리하는 로직 구현",
        component="Supervisor",
        dependencies=["sv-001", "sv-002"],
        technologies=["State Machine", "Event Sourcing"],
        deliverables=["report_aggregator.py", "state_transition.py"]
    ),
    Task(
        id="sv-004",
        name="추가 Tool/Agent 호출 룰 작성",
        description="집계된 정보를 바탕으로 추가 Tool/Agent 호출을 결정하는 룰 작성",
        component="Supervisor",
        dependencies=["sv-003"],
        technologies=["Decision Trees", "Rule Engine"],
        deliverables=["decision_rules.py", "tool_agent_selector.py"]
    ),
    Task(
        id="sv-005",
        name="Chat Gateway 연동 구현",
        description="Chat Gateway와 연동하여 사용자 응답을 처리하는 구현",
        component="Supervisor",
        technologies=["HTTP Client", "WebSockets"],
        deliverables=["chat_gateway_client.py", "user_response_handler.py"]
    ),
    Task(
        id="sv-006",
        name="SSE 응답 스트리밍 구현",
        description="SSE를 통한 응답 스트리밍 구현",
        component="Supervisor",
        dependencies=["sv-005"],
        technologies=["SSE", "Async Streams"],
        deliverables=["sse_streamer.py", "response_formatter.py"]
    ),
    Task(
        id="sv-007",
        name="시나리오별 워크플로우 테스트 작성",
        description="다양한 시나리오에 대한 워크플로우 테스트 작성",
        component="Supervisor",
        dependencies=["sv-003", "sv-004", "sv-006"],
        technologies=["pytest", "Workflow Testing"],
        deliverables=["test_workflows.py", "scenarios/"]
    )
]

# ----- MCP Server 컴포넌트 태스크 -----
MCP_SERVER_TASKS = [
    Task(
        id="mcp-001",
        name="요청 스케줄러 구현",
        description="Tool 실행 요청을 스케줄링하는 구현",
        component="MCP Server",
        priority=TaskPriority.HIGH,
        technologies=["Task Scheduler", "Queue Management"],
        deliverables=["request_scheduler.py", "priority_queue.py"]
    ),
    Task(
        id="mcp-002",
        name="Docker 컨테이너 런처 구현",
        description="Tool을 Docker 컨테이너로 실행하는 런처 구현",
        component="MCP Server",
        technologies=["Docker API", "Container Management"],
        deliverables=["container_launcher.py", "docker_client.py"]
    ),
    Task(
        id="mcp-003",
        name="실행별 컨텍스트 저장소 설계",
        description="DB 또는 KV 기반 실행 컨텍스트 저장소 설계",
        component="MCP Server",
        technologies=["Database Design", "KV Store"],
        deliverables=["context_store_schema.md", "db_migrations/"]
    ),
    Task(
        id="mcp-004",
        name="컨텍스트 저장소 구현",
        description="실행 컨텍스트 저장소 구현",
        component="MCP Server",
        dependencies=["mcp-003"],
        technologies=["ORM", "Redis", "MongoDB"],
        deliverables=["context_store.py", "db_adapter.py"]
    ),
    Task(
        id="mcp-005",
        name="취소 토큰 발행·전파 구현",
        description="실행 취소를 위한 토큰 발행 및 전파 구현",
        component="MCP Server",
        technologies=["Cancellation Tokens", "Signal Handling"],
        deliverables=["cancellation_token.py", "token_propagator.py"]
    ),
    Task(
        id="mcp-006",
        name="SSE/WebSocket 구현",
        description="상태 이벤트 스트리밍을 위한 SSE/WebSocket 구현",
        component="MCP Server",
        technologies=["SSE", "WebSockets", "Async IO"],
        deliverables=["event_streamer.py", "websocket_handler.py"]
    ),
    Task(
        id="mcp-007",
        name="장시간 실행 도구 취소 검증 테스트 작성",
        description="장시간 실행되는 도구의 취소 기능 검증 테스트 작성",
        component="MCP Server",
        dependencies=["mcp-002", "mcp-005"],
        technologies=["Integration Testing", "Long-running Tests"],
        deliverables=["test_long_running_cancellation.py"]
    ),
    Task(
        id="mcp-008",
        name="상태 이벤트 순서·지속성 검증 테스트 작성",
        description="상태 이벤트의 순서 및 지속성 검증 테스트 작성",
        component="MCP Server",
        dependencies=["mcp-004", "mcp-006"],
        technologies=["Event Ordering", "Persistence Testing"],
        deliverables=["test_event_ordering.py", "test_persistence.py"]
    )
]

# ----- Tool Registry 컴포넌트 태스크 -----
TOOL_REGISTRY_TASKS = [
    Task(
        id="tr-001",
        name="Tool 스키마 설계",
        description="도구 이름/버전/설명을 포함한 스키마 설계",
        component="Tool Registry",
        technologies=["Database Design", "Schema Design"],
        deliverables=["tool_schema.md", "db_migrations/"]
    ),
    Task(
        id="tr-002",
        name="메타데이터 DB 구현",
        description="도구 메타데이터 DB 구현",
        component="Tool Registry",
        dependencies=["tr-001"],
        technologies=["PostgreSQL", "MongoDB", "ORM"],
        deliverables=["metadata_store.py", "db_models.py"]
    ),
    Task(
        id="tr-003",
        name="CI 빌드 파이프라인 구성",
        description="컨테이너 이미지 태깅 및 푸시를 위한 CI 파이프라인 구성",
        component="Tool Registry",
        technologies=["CI/CD", "Docker", "GitHub Actions"],
        deliverables=["ci_pipeline.yaml", "build_scripts/"]
    ),
    Task(
        id="tr-004",
        name="캐시 레이어 구현",
        description="CDN 또는 Redis 기반 캐시 프론트 구현",
        component="Tool Registry",
        technologies=["Redis", "CDN", "Cache Management"],
        deliverables=["cache_layer.py", "invalidation.py"]
    ),
    Task(
        id="tr-005",
        name="버전 호환성 검증 스크립트 작성",
        description="도구 버전 간 호환성을 검증하는 스크립트 작성",
        component="Tool Registry",
        dependencies=["tr-002"],
        technologies=["Semantic Versioning", "Compatibility Testing"],
        deliverables=["version_validator.py", "compatibility_test.py"]
    )
]

# ----- Observability 컴포넌트 태스크 -----
OBSERVABILITY_TASKS = [
    Task(
        id="obs-001",
        name="OpenTelemetry SDK 적용",
        description="각 서비스에 OpenTelemetry SDK 적용",
        component="Observability",
        technologies=["OpenTelemetry", "Instrumentation"],
        deliverables=["telemetry.py", "tracer.py", "meter.py"]
    ),
    Task(
        id="obs-002",
        name="Fluentd/Logstash 파이프라인 구성",
        description="로그 수집을 위한 Fluentd/Logstash 파이프라인 구성",
        component="Observability",
        technologies=["Fluentd", "Logstash", "ELK Stack"],
        deliverables=["fluentd.conf", "logstash.conf", "log_pipeline.yaml"]
    ),
    Task(
        id="obs-003",
        name="Prometheus scrape 설정",
        description="메트릭 수집을 위한 Prometheus scrape 설정",
        component="Observability",
        technologies=["Prometheus", "Metrics", "ServiceMonitor"],
        deliverables=["prometheus.yaml", "service-monitors/"]
    ),
    Task(
        id="obs-004",
        name="Grafana 대시보드 작성",
        description="시스템 모니터링을 위한 Grafana 대시보드 작성",
        component="Observability",
        dependencies=["obs-003"],
        technologies=["Grafana", "Dashboard Design"],
        deliverables=["dashboards/system_overview.json", "dashboards/component_details.json"]
    ),
    Task(
        id="obs-005",
        name="Alertmanager 룰 작성",
        description="이상 징후 감지를 위한 Alertmanager 룰 작성",
        component="Observability",
        dependencies=["obs-003"],
        technologies=["Alertmanager", "Alert Rules"],
        deliverables=["alertmanager.yaml", "alert_rules/"]
    )
]

# 전체 태스크 맵
ALL_TASKS = (
    EVENT_GATEWAY_TASKS +
    CHAT_GATEWAY_TASKS +
    SUB_AGENT_TASKS +
    SUPERVISOR_TASKS +
    MCP_SERVER_TASKS +
    TOOL_REGISTRY_TASKS +
    OBSERVABILITY_TASKS
)

# 컴포넌트별 태스크 맵
COMPONENT_TASKS = {
    "Event Gateway": EVENT_GATEWAY_TASKS,
    "Chat Gateway": CHAT_GATEWAY_TASKS,
    "Sub-Agent": SUB_AGENT_TASKS,
    "Supervisor": SUPERVISOR_TASKS,
    "MCP Server": MCP_SERVER_TASKS,
    "Tool Registry": TOOL_REGISTRY_TASKS,
    "Observability": OBSERVABILITY_TASKS
}


def get_tasks_by_component(component: str) -> List[Task]:
    """컴포넌트별 태스크 목록 조회"""
    return COMPONENT_TASKS.get(component, [])


def get_task_by_id(task_id: str) -> Optional[Task]:
    """태스크 ID로 태스크 조회"""
    for task in ALL_TASKS:
        if task.id == task_id:
            return task
    return None


def get_dependent_tasks(task_id: str) -> List[Task]:
    """특정 태스크에 의존하는 태스크 목록 조회"""
    dependent_tasks = []
    for task in ALL_TASKS:
        if task_id in task.dependencies:
            dependent_tasks.append(task)
    return dependent_tasks


if __name__ == "__main__":
    # 컴포넌트별 태스크 출력 예시
    print("=== A2A와 MCP 통합 MSA 아키텍처 구현 태스크 ===")
    
    for component, tasks in COMPONENT_TASKS.items():
        print(f"\n## {component} 컴포넌트 ({len(tasks)} 태스크)")
        for task in tasks:
            print(f"- [{task.status.value}] {task.id}: {task.name}")
            print(f"  우선순위: {task.priority.value}, 예상 시간: {task.estimated_hours}시간")
            if task.dependencies:
                print(f"  의존성: {', '.join(task.dependencies)}") 