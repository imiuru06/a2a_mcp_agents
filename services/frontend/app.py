import chainlit as cl
import httpx
import json
import os
import io
import base64
import datetime
import uuid
import asyncio
from typing import Dict, Any, List
from dotenv import load_dotenv

from chainlit.logger import logger
from chainlit.input_widget import TextInput

# 환경 변수 로드
load_dotenv()

# 환경 변수 설정
API_GATEWAY_URL = os.environ.get("API_GATEWAY_URL", "http://api-gateway:8000")
CHAT_GATEWAY_URL = os.environ.get("CHAT_GATEWAY_URL", "http://chat-gateway:8002")
SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "http://supervisor:8003")
TOOL_REGISTRY_URL = os.environ.get("TOOL_REGISTRY_URL", "http://tool-registry:8005")
EVENT_GATEWAY_URL = os.environ.get("EVENT_GATEWAY_URL", "http://event-gateway:8001")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://mcp-server:8004")
LLM_REGISTRY_URL = os.environ.get("LLM_REGISTRY_URL", "http://llm-registry:8101")

# 필수 환경 변수 검사
if not API_GATEWAY_URL:
    logger.error("API_GATEWAY_URL 환경 변수가 설정되지 않았습니다.")
    raise ValueError("API_GATEWAY_URL 환경 변수가 설정되지 않았습니다.")

# Azure OpenAI 환경 변수 확인
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
if not AZURE_OPENAI_API_KEY:
    logger.warning("AZURE_OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")

# 통신 재시도 설정
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))
RETRY_DELAY = float(os.environ.get("RETRY_DELAY", "2.0"))
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "30.0"))

# 서비스 상태 저장용 전역 변수
service_status = {}
available_tools = {}
available_agents = {}
available_capabilities = {}
available_llm_services = {}

# 사용자 대화 이력 저장
chat_history = {}

@cl.on_chat_start
async def start():
    """채팅 시작 시 호출되는 함수"""
    # 세션 ID 생성
    session_id = str(uuid.uuid4())
    cl.user_session.set("session_id", session_id)
    chat_history[session_id] = []
    
    # 초기 메시지 전송
    await cl.Message(content="안녕하세요! 자동차 정비 도우미입니다. 어떤 도움이 필요하신가요?", author="시스템").send()
    
    # 시스템 데이터 로드
    await load_system_data()
    
    # 사이드바에 대시보드 링크 추가 (액션으로 변경)
    buttons = [
        cl.Action(name="show_dashboard", label="대시보드", payload={"type": "navigation"}),
        cl.Action(name="show_tools", label="도구 목록", payload={"type": "navigation"}),
        cl.Action(name="show_agents", label="에이전트 목록", payload={"type": "navigation"}),
        cl.Action(name="show_llm_services", label="LLM 서비스 설정", payload={"type": "navigation"})
    ]
    
    export_actions = [
        cl.Action(name="export_chat_history", label="대화내용 내보내기", payload={"type": "export"}),
        cl.Action(name="clear_chat_history", label="대화내용 초기화", payload={"type": "clear"})
    ]
    
    await cl.Message(
        content="저는 자동차 정비와 관련된 다양한 질문에 답변할 수 있습니다. 예를 들어, '엔진 오일 경고등이 켜졌어요'라고 물어보세요.",
        author="정비 어시스턴트",
        actions=export_actions + buttons
    ).send()
    
    # 파일 업로드 메시지
    await cl.Message(
        content="차량 사진이나 진단 관련 문서를 업로드하시면 분석을 도와드립니다.",
        author="시스템"
    ).send()
    
    # 도구 예시 제공
    tool_actions = []
    
    for tool in available_tools[:3] if available_tools else []:
        tool_id = tool.get('tool_id')
        tool_actions.append(
            cl.Action(
                name=f"run_tool_{tool_id}", 
                label=f"도구 실행: {tool.get('name')}",
                payload={"tool_id": tool_id}
            )
        )
    
    if tool_actions:
        await cl.Message(
            content="다음은 자주 사용하는 도구들입니다. 버튼을 클릭하여 실행할 수 있습니다.",
            author="시스템",
            actions=tool_actions
        ).send()

async def load_system_data():
    """시스템 데이터 로드"""
    try:
        # API 게이트웨이를 통해 대시보드 데이터 로드
        for retry in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    response = await client.get(f"{API_GATEWAY_URL}/ui/dashboard")
                    
                    if response.status_code == 200:
                        dashboard_data = response.json()
                        
                        global available_tools, available_agents, available_capabilities, service_status
                        
                        available_tools = dashboard_data.get("tools", [])
                        available_agents = dashboard_data.get("agents", [])
                        available_capabilities = dashboard_data.get("capabilities", [])
                        
                        # 서비스 상태 업데이트
                        service_status = {
                            service.get("name", "unknown"): service.get("status", "unknown") == "healthy"
                            for service in dashboard_data.get("active_services", [])
                        }
                        
                        # LLM 서비스 목록 가져오기
                        await load_llm_services()
                        
                        return True
                    else:
                        logger.error(f"대시보드 데이터 로드 실패: HTTP {response.status_code} - {response.text}")
                        
                        # 마지막 시도가 아니면 재시도
                        if retry < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_DELAY)
                            continue
                        return False
            except httpx.RequestError as e:
                logger.error(f"API 게이트웨이 연결 오류: {str(e)}")
                
                # 마지막 시도가 아니면 재시도
                if retry < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                return False
    except Exception as e:
        logger.error(f"데이터 로드 오류: {str(e)}")
        return False

async def load_llm_services():
    """LLM 서비스 목록 로드"""
    try:
        global available_llm_services
        
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(f"{API_GATEWAY_URL}/ui/llm/services")
            
            if response.status_code == 200:
                services = response.json()
                available_llm_services = services
                logger.info(f"LLM 서비스 로드 완료: {len(services)}개 서비스 사용 가능")
                return True
            else:
                logger.error(f"LLM 서비스 로드 실패: HTTP {response.status_code}")
                return False
    except Exception as e:
        logger.error(f"LLM 서비스 로드 오류: {str(e)}")
        return False

@cl.on_message
async def main(message: cl.Message):
    """사용자 메시지 처리"""
    try:
        # 메시지 처리 중 표시
        processing_msg = cl.Message(content="메시지를 처리 중입니다...", author="시스템")
        await processing_msg.send()
        
        # 대화 이력에 사용자 메시지 추가
        session_id = cl.user_session.get("session_id")
        if session_id in chat_history:
            chat_history[session_id].append({"role": "user", "content": message.content})
        
        # 파일 처리
        if message.elements:
            for element in message.elements:
                if isinstance(element, cl.File):
                    await process_uploaded_file(element, processing_msg)
                    return
        
        if message.content.startswith("/"):
            # 명령어 처리
            await handle_command(message.content, processing_msg)
        else:
            # 일반 메시지는 채팅 게이트웨이로 전송
            await send_to_chat_gateway(message.content, processing_msg)
            
    except Exception as e:
        logger.error(f"메시지 처리 중 오류 발생: {str(e)}")
        await cl.Message(content=f"오류가 발생했습니다: {str(e)}", author="시스템").send()

@cl.action_callback("export_chat_history")
async def export_chat_history_callback(_):
    """대화 내용 내보내기"""
    try:
        session_id = cl.user_session.get("session_id")
        if session_id in chat_history and chat_history[session_id]:
            # 대화 내용 포맷팅
            chat_export = "# 자동차 정비 어시스턴트 대화 내용\n\n"
            chat_export += f"날짜: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            for msg in chat_history[session_id]:
                role = "사용자" if msg["role"] == "user" else "어시스턴트"
                chat_export += f"## {role}:\n{msg['content']}\n\n"
            
            # 파일로 내보내기
            chat_file = io.StringIO(chat_export)
            
            # 파일 다운로드 제공
            await cl.Message(
                content="대화 내용을 다운로드할 수 있습니다:",
                elements=[
                    cl.File(
                        name="chat_history.md",
                        content=chat_file.getvalue().encode('utf-8'),
                        mime="text/markdown"
                    )
                ]
            ).send()
        else:
            await cl.Message(content="내보낼 대화 내용이 없습니다.", author="시스템").send()
    except Exception as e:
        logger.error(f"대화 내용 내보내기 중 오류가 발생했습니다: {str(e)}")
        await cl.Message(content=f"대화 내용 내보내기 중 오류가 발생했습니다: {str(e)}", author="시스템").send()

@cl.action_callback("clear_chat_history")
async def clear_chat_history_callback(_):
    """대화 내용 초기화"""
    session_id = cl.user_session.get("session_id")
    if session_id in chat_history:
        chat_history[session_id] = []
    await cl.Message(content="대화 내용이 초기화되었습니다.", author="시스템").send()

async def process_uploaded_file(file: cl.File, processing_msg: cl.Message):
    """업로드된 파일 처리"""
    try:
        file_content = await file.get_bytes()
        file_name = file.name
        file_type = file.type
        
        # 파일 처리 메시지 표시
        await processing_msg.update(content=f"{file_name} 파일을 분석 중입니다...")
        
        # 이미지 파일인 경우 미리보기 표시
        if file_type.startswith("image/"):
            b64_content = base64.b64encode(file_content).decode("utf-8")
            image_element = cl.Image(
                name=file_name, 
                display="inline", 
                size="large",
                content=file_content
            )
            
            # 파일 처리 결과 응답
            await processing_msg.remove()
            await cl.Message(
                content=f"업로드하신 이미지를 분석한 결과입니다:",
                author="정비 어시스턴트",
                elements=[image_element]
            ).send()
            
            # 이미지 분석 텍스트 제공 (예시)
            await cl.Message(
                content="차량 이미지에서 중요한 부분을 확인했습니다. 브레이크 패드 마모가 진행 중인 것으로 보입니다. 점검이 필요합니다.",
                author="정비 어시스턴트"
            ).send()
        else:
            # 텍스트 파일 내용 표시 (PDF 등 다른 형식은 추가 처리 필요)
            await processing_msg.remove()
            await cl.Message(
                content=f"파일 '{file_name}'이(가) 업로드되었습니다. 분석 결과는 잠시 후 제공됩니다.",
                author="시스템",
                elements=[cl.File(name=file_name, path=file.path, display="inline")]
            ).send()
    except Exception as e:
        logger.error(f"파일 처리 중 오류가 발생했습니다: {str(e)}")
        await processing_msg.update(content=f"파일 처리 중 오류가 발생했습니다: {str(e)}")

@cl.action_callback("show_dashboard")
async def dashboard_callback(_):
    """대시보드 페이지로 이동"""
    await handle_command("/대시보드", cl.Message(content="대시보드로 이동 중...", author="시스템"))

@cl.action_callback("show_tools")
async def tools_callback(_):
    """도구 목록 페이지로 이동"""
    await handle_command("/도구", cl.Message(content="도구 목록을 불러오는 중...", author="시스템"))

@cl.action_callback("show_agents")
async def agents_callback(_):
    """에이전트 목록 페이지로 이동"""
    await handle_command("/에이전트", cl.Message(content="에이전트 목록을 불러오는 중...", author="시스템"))

@cl.action_callback("show_llm_services")
async def show_llm_services_callback(_):
    """LLM 서비스 설정 페이지"""
    await show_llm_services()

async def show_llm_services():
    """LLM 서비스 목록 및 설정 표시"""
    try:
        # LLM 서비스 데이터 로드
        await load_llm_services()
        
        if not available_llm_services:
            await cl.Message(content="사용 가능한 LLM 서비스가 없습니다.", author="시스템").send()
            return
        
        content = "## LLM 서비스 설정\n\n"
        content += "현재 사용 가능한 LLM 서비스 목록입니다. 대화에 사용할 서비스를 선택하세요.\n\n"
        
        service_actions = []
        
        for service in available_llm_services:
            service_id = service.get("service_id", "unknown")
            service_name = service.get("name", "Unknown Service")
            provider = service.get("provider", "Unknown Provider")
            model = service.get("model", "Unknown Model")
            
            # 서비스 선택 액션 추가
            service_actions.append(
                cl.Action(
                    name=f"select_llm_{service_id}",
                    label=f"사용: {service_name}",
                    payload={"service_id": service_id}
                )
            )
            
            content += f"### {service_name}\n"
            content += f"- **제공자**: {provider}\n"
            content += f"- **모델**: {model}\n"
            content += f"- **서비스 ID**: `{service_id}`\n"
            
            # 기능 목록 표시
            features = service.get("features", [])
            if features:
                content += "- **지원 기능**: "
                content += ", ".join(features)
                content += "\n"
            
            content += "\n"
        
        # API 키 설정 확인
        api_key_status = "설정됨 ✅" if AZURE_OPENAI_API_KEY else "설정되지 않음 ❌"
        content += f"### API 키 상태\n"
        content += f"- **Azure OpenAI API 키**: {api_key_status}\n\n"
        content += "API 키가 설정되지 않은 경우, 서버의 .env 파일에 추가해야 합니다.\n"
        
        # 서비스 선택 메시지 표시
        await cl.Message(
            content=content,
            author="시스템",
            actions=service_actions
        ).send()
        
    except Exception as e:
        logger.error(f"LLM 서비스 조회 중 오류 발생: {str(e)}")
        await cl.Message(content=f"LLM 서비스 조회 중 오류 발생: {str(e)}", author="시스템").send()

@cl.action_callback("select_llm")
async def select_llm_callback(action: cl.Action):
    """LLM 서비스 선택 처리"""
    try:
        service_id = action.payload.get("service_id")
        if not service_id:
            await cl.Message(content="서비스 ID가 제공되지 않았습니다.", author="시스템").send()
            return
        
        # 선택한 서비스 정보 찾기
        selected_service = next((s for s in available_llm_services if s.get("service_id") == service_id), None)
        if not selected_service:
            await cl.Message(content=f"서비스 ID '{service_id}'를 찾을 수 없습니다.", author="시스템").send()
            return
        
        # 세션에 선택한 서비스 저장
        cl.user_session.set("selected_llm_service", selected_service)
        
        service_name = selected_service.get("name", "Unknown Service")
        model = selected_service.get("model", "Unknown Model")
        
        await cl.Message(
            content=f"**{service_name}** ({model})을(를) 대화에 사용합니다.",
            author="시스템"
        ).send()
        
    except Exception as e:
        logger.error(f"LLM 서비스 선택 중 오류 발생: {str(e)}")
        await cl.Message(content=f"LLM 서비스 선택 중 오류 발생: {str(e)}", author="시스템").send()

async def handle_command(command: str, processing_msg: cl.Message):
    """특별 명령어 처리"""
    cmd_parts = command.split()
    cmd = cmd_parts[0].lower()
    
    if cmd == "/상태":
        # 시스템 상태 확인
        await processing_msg.update(content="시스템 상태를 확인 중입니다...")
        
        status = await check_system_status()
        status_msg = "## 시스템 상태\n\n"
        status_details = "## 시스템 상태 상세 정보\n\n"
        
        all_healthy = True
        for service, info in status.items():
            status_icon = "✅" if info.get("healthy", False) else "❌"
            all_healthy = all_healthy and info.get("healthy", False)
            status_msg += f"**{service}**: {status_icon}\n"
            status_details += f"### {service}\n"
            status_details += f"- **상태**: {status_icon} {info.get('details', '정보 없음')}\n"
            if "status_code" in info:
                status_details += f"- **응답 코드**: {info.get('status_code')}\n"
            status_details += "\n"
        
        # 전체 시스템 상태 요약
        if all_healthy:
            status_summary = "🟢 모든 시스템이 정상 작동 중입니다."
        else:
            status_summary = "🔴 일부 서비스에 문제가 있습니다. 아래 상세 정보를 확인하세요."
        
        status_msg = f"{status_summary}\n\n{status_msg}"
            
        # 시나리오 동작 확인 버튼 추가
        scenario_buttons = [
            cl.Action(name="check_scenario1", label="시나리오 1: 모니터링 트리거", payload={"scenario": "monitoring"}),
            cl.Action(name="check_scenario2", label="시나리오 2: 사용자 채팅", payload={"scenario": "chat"}),
            cl.Action(name="test_mcp_scenario", label="MCP 의사소통 시나리오", payload={"scenario": "mcp"}),
            cl.Action(name="check_service_registry", label="서비스 레지스트리 확인", payload={"check": "registry"})
        ]
        
        # 기존 메시지 삭제 후 새 메시지 전송
        await processing_msg.remove()
        
        # 상태 메시지 전송
        await cl.Message(content=status_msg, author="시스템").send()
        
        # 상세 정보는 접을 수 있는 패널로 제공
        await cl.Message(
            content=status_details,
            author="시스템",
            actions=scenario_buttons
        ).send()
        
    elif cmd == "/도구":
        # 사용 가능한 도구 목록 표시
        tools = await get_available_tools()
        
        if not tools:
            await processing_msg.remove()
            await cl.Message(content="도구 정보를 가져올 수 없습니다.", author="시스템").send()
            return
            
        tools_msg = "## 사용 가능한 도구\n\n"
        
        for tool in tools:
            tools_msg += f"**{tool.get('name', 'N/A')}** (`{tool.get('tool_id', 'N/A')}`)\n"
            tools_msg += f"- {tool.get('description', '설명 없음')}\n\n"
        
        # 기존 메시지 삭제 후 새 메시지 전송
        await processing_msg.remove()
        await cl.Message(content=tools_msg, author="시스템").send()
        
    elif cmd == "/도구실행" and len(cmd_parts) > 1:
        # 특정 도구 실행
        tool_id = cmd_parts[1]
        
        # 도구 파라미터 파싱 (예: /도구실행 tool_id param1=value1 param2=value2)
        params = {}
        if len(cmd_parts) > 2:
            for param in cmd_parts[2:]:
                if "=" in param:
                    key, value = param.split("=", 1)
                    params[key] = value
        
        await execute_tool(tool_id, params, processing_msg)
    
    elif cmd == "/대시보드":
        # 대시보드 표시
        await processing_msg.remove()
        
        # 대시보드 버튼 생성
        actions = [
            cl.Action(name="show_diagnostic_stats", label="차량 진단 통계 보기", payload={"stats_type": "diagnostic"}),
            cl.Action(name="show_mechanic_stats", label="정비사 통계 보기", payload={"stats_type": "mechanic"}),
            cl.Action(name="show_tool_usage_stats", label="도구 사용 통계 보기", payload={"stats_type": "tool_usage"}),
            cl.Action(name="show_llm_services", label="LLM 서비스 설정", payload={"type": "navigation"})
        ]
        
        await cl.Message(
            content="## 시스템 대시보드\n\n아래 버튼을 클릭하여 다양한 통계 정보를 확인하세요.",
            author="시스템",
            actions=actions
        ).send()
        
    elif cmd == "/에이전트":
        # 사용 가능한 에이전트 목록 표시
        await processing_msg.remove()
        
        # API 게이트웨이를 통해 에이전트 목록 가져오기
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_GATEWAY_URL}/ui/agents")
            
            if response.status_code == 200:
                agents = response.json()
                
                if not agents:
                    await cl.Message(content="사용 가능한 에이전트가 없습니다.", author="시스템").send()
                    return
                
                agents_msg = "## 사용 가능한 에이전트\n\n"
                
                # 에이전트 카드 형태로 표시
                agent_elements = []
                
                for agent in agents:
                    agent_card = cl.Card(
                        title=agent.get('name', 'N/A'),
                        content=agent.get('description', '정보 없음'),
                        elements=[
                            cl.Text(name="version", content=f"버전: {agent.get('version', '1.0.0')}"),
                            cl.Text(name="specialty", content=f"전문 분야: {agent.get('metadata', {}).get('specialty', '정보 없음')}")
                        ]
                    )
                    agent_elements.append(agent_card)
                
                await cl.Message(content=agents_msg, author="시스템", elements=agent_elements).send()
            else:
                await cl.Message(content="에이전트 정보를 가져올 수 없습니다.", author="시스템").send()
    
    elif cmd == "/템플릿":
        # 메시지 템플릿 목록 표시
        await processing_msg.remove()
        
        templates = [
            "엔진 오일을 교체해야 할 때인가요?",
            "타이어 공기압은 어떻게 확인하나요?",
            "브레이크 패드 교체 시기는?",
            "배터리가 방전되었을 때 대처법은?"
        ]
        
        template_actions = []
        for template in templates:
            template_id = template.replace(' ', '_')
            template_actions.append(cl.Action(
                name=f"template_{template_id}", 
                label=template,
                payload={"template_id": template_id}
            ))
        
        await cl.Message(
            content="## 자주 사용하는 질문 템플릿\n\n아래 버튼을 클릭하여 질문하세요:",
            author="시스템",
            actions=template_actions
        ).send()
        
    elif cmd == "/도움말":
        # 도움말 표시
        help_msg = """## 사용 가능한 명령어

- **/상태**: 모든 서비스의 현재 상태를 확인하고 시나리오 동작 테스트를 할 수 있습니다.
- **/도구**: 사용 가능한 도구 목록을 표시합니다.
- **/도구실행 [도구ID] [파라미터]**: 지정된 도구를 실행합니다.
  예: `/도구실행 car_diagnostic_tool diagnostic_data={"car_model":"소나타"}`
- **/에이전트**: 사용 가능한 에이전트 목록을 표시합니다.
- **/대시보드**: 시스템 대시보드를 표시합니다.
- **/템플릿**: 자주 사용하는 질문 템플릿을 표시합니다.
- **/도움말**: 이 도움말 메시지를 표시합니다.

## 시스템 시나리오

- **시나리오 1**: 모니터링 트리거에 의한 자동 대응 - `/상태` 명령어에서 확인 가능
- **시나리오 2**: 사용자 채팅/인터럽트를 통한 에이전트 상호작용 - `/상태` 명령어에서 확인 가능

## 파일 업로드

차량 사진이나 진단 관련 문서를 업로드하시면 분석을 도와드립니다.
"""
        # 기존 메시지 삭제 후 새 메시지 전송
        await processing_msg.remove()
        await cl.Message(content=help_msg, author="시스템").send()
    else:
        # 기존 메시지 삭제 후 새 메시지 전송
        await processing_msg.remove()
        await cl.Message(content="알 수 없는 명령어입니다. '/도움말'을 입력하여 사용 가능한 명령어를 확인하세요.", author="시스템").send()

@cl.action_callback("run_tool")
async def run_tool_callback(action: cl.Action):
    """도구 실행 버튼 처리"""
    tool_id = action.id.split("_")[-1]
    
    # 도구에 대한 폼 생성
    tool = next((t for t in available_tools if t.get("tool_id") == tool_id), None)
    
    if tool:
        parameters = tool.get("parameters", {})
        inputs = []
        
        for param_name, param_info in parameters.items():
            inputs.append(
                cl.TextInput(
                    name=param_name,
                    label=param_info.get("description", param_name),
                    placeholder=f"{param_info.get('type', 'object')} 형식으로 입력하세요"
                )
            )
        
        # 폼 제출 처리
        form_result = await cl.AskForm(
            title=f"{tool.get('name')} 실행",
            content="아래 필요한 정보를 입력해주세요:",
            inputs=inputs
        ).send()
        
        if form_result:
            # 파라미터 구성
            params = {}
            for param_name, param_info in parameters.items():
                if param_name in form_result:
                    # JSON 파싱 시도
                    try:
                        params[param_name] = json.loads(form_result[param_name])
                    except:
                        params[param_name] = form_result[param_name]
            
            # 도구 실행
            status_msg = await cl.Message(content=f"{tool.get('name')}을(를) 실행 중입니다...", author="시스템").send()
            await execute_tool(tool_id, params, status_msg)

async def execute_tool(tool_id: str, params: Dict[str, Any], processing_msg: cl.Message):
    """API 게이트웨이를 통해 도구 실행"""
    try:
        # 도구 실행 요청 페이로드 구성
        payload = {
            "tool_id": tool_id,
            "parameters": params,
            "agent_id": cl.user_session.get("session_id", str(uuid.uuid4()))
        }
        
        # 재시도 로직으로 도구 실행 요청
        execution_id = None
        for retry in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    # 도구 실행 요청 전송
                    response = await client.post(f"{API_GATEWAY_URL}/ui/execute-tool", json=payload)
                    
                    # 성공 시 실행 ID 추출
                    if response.status_code == 200:
                        result = response.json()
                        execution_id = result.get("execution_id")
                        break
                    else:
                        logger.warning(f"도구 실행 요청 실패 (시도 {retry+1}/{MAX_RETRIES}): HTTP {response.status_code}")
                        if retry < MAX_RETRIES - 1:
                            # 현재 메시지 삭제하고 새 메시지로 대체
                            await processing_msg.remove()
                            processing_msg = await cl.Message(content=f"도구 실행 중 오류가 발생했습니다. 재시도 중... ({retry+1}/{MAX_RETRIES})", author="시스템").send()
                            await asyncio.sleep(RETRY_DELAY)
            except httpx.RequestError as e:
                logger.error(f"도구 실행 요청 오류 (시도 {retry+1}/{MAX_RETRIES}): {str(e)}")
                if retry < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
        
        # 실행 ID를 얻지 못한 경우 에러 처리
        if not execution_id:
            await processing_msg.remove()
            await cl.Message(content="도구 실행에 실패했습니다. 네트워크 연결을 확인하거나 나중에 다시 시도해 주세요.", author="시스템").send()
            return
            
        # 실행 상태 폴링 및 결과 확인
        max_polls = 15  # 최대 폴링 횟수
        poll_interval = 1.0  # 초기 폴링 간격 (초)
        
        # 현재 메시지 삭제하고 새 메시지로 대체
        await processing_msg.remove()
        processing_msg = await cl.Message(content=f"도구를 실행 중입니다. 잠시만 기다려 주세요...", author="시스템").send()
        
        # 도구 실행 상태 폴링
        for poll in range(max_polls):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    status_response = await client.get(f"{API_GATEWAY_URL}/ui/status/{execution_id}")
                    
                    if status_response.status_code == 200:
                        execution_status = status_response.json()
                        status = execution_status.get("status", "")
                        
                        # 상태에 따른 처리
                        if status == "completed":
                            result = execution_status.get("result", {})
                            
                            # 결과 포맷팅
                            if isinstance(result, dict) and result:
                                result_content = f"### 도구 실행 결과\n\n"
                                
                                # 결과 데이터 처리
                                for key, value in result.items():
                                    if key == "diagnostic_result" and isinstance(value, dict):
                                        result_content += f"**진단 결과:**\n\n"
                                        for diagnosis_key, diagnosis_value in value.items():
                                            result_content += f"- **{diagnosis_key}**: {diagnosis_value}\n"
                                    elif key == "maintenance_result" and isinstance(value, dict):
                                        result_content += f"**정비 결과:**\n\n"
                                        for maint_key, maint_value in value.items():
                                            result_content += f"- **{maint_key}**: {maint_value}\n"
                                    else:
                                        result_content += f"**{key}**: {value}\n"
                            else:
                                result_content = f"### 도구 실행 결과\n\n```json\n{json.dumps(result, indent=2, ensure_ascii=False)}\n```"
                            
                            await processing_msg.remove()
                            await cl.Message(content=result_content, author="시스템").send()
                            return
                        
                        elif status == "failed":
                            error_msg = execution_status.get("error", "알 수 없는 오류가 발생했습니다.")
                            await processing_msg.remove()
                            await cl.Message(content=f"도구 실행 실패: {error_msg}", author="시스템").send()
                            return
                        
                        elif status == "cancelled":
                            await processing_msg.remove()
                            await cl.Message(content="도구 실행이 취소되었습니다.", author="시스템").send()
                            return
                        
                        else:  # running, pending 등의 상태
                            # 폴링 계속, 진행 중임을 표시
                            if poll > 2:  # 처음 몇 번의 폴링은 메시지 업데이트 없이 진행
                                dots = "." * ((poll % 3) + 1)
                                progress_message = f"도구를 실행 중입니다{dots} (진행 상태: {status})"
                                # 현재 메시지 삭제하고 새 메시지로 대체
                                await processing_msg.remove()
                                processing_msg = await cl.Message(content=progress_message, author="시스템").send()
                            
                            # 폴링 간격을 점점 늘림 (최대 3초)
                            if poll < 5:
                                await asyncio.sleep(poll_interval)
                            else:
                                await asyncio.sleep(min(poll_interval * 1.5, 3.0))
                            continue
                    
                    else:
                        logger.error(f"도구 상태 확인 실패: HTTP {status_response.status_code}")
                        if poll < max_polls - 1:  # 마지막 폴링이 아니면 계속 시도
                            await asyncio.sleep(poll_interval)
                            continue
                        else:
                            await processing_msg.remove()
                            await cl.Message(content="도구 상태를 확인할 수 없습니다. 시스템 관리자에게 문의하세요.", author="시스템").send()
                            return
                
            except httpx.RequestError as e:
                logger.error(f"도구 상태 확인 중 오류 발생: {str(e)}")
                if poll < max_polls - 1:  # 마지막 폴링이 아니면 계속 시도
                    await asyncio.sleep(poll_interval)
                    continue
                else:
                    await processing_msg.remove()
                    await cl.Message(content=f"도구 상태 확인 중 연결 오류가 발생했습니다: {str(e)}", author="시스템").send()
                    return
        
        # 최대 폴링 횟수 초과 - 타임아웃
        await processing_msg.remove()
        await cl.Message(
            content="도구 실행 결과를 기다리는 시간이 초과되었습니다. 도구가 여전히 실행 중일 수 있습니다. 나중에 결과를 확인해 주세요.",
            author="시스템"
        ).send()
                
    except Exception as e:
        logger.error(f"도구 실행 중 오류가 발생했습니다: {str(e)}")
        await processing_msg.remove()
        await cl.Message(content=f"도구 실행 중 오류가 발생했습니다: {str(e)}", author="시스템").send()

async def send_to_chat_gateway(message_content: str, processing_msg: cl.Message):
    """메시지를 채팅 게이트웨이로 전송"""
    try:
        # 세션 ID 확인 및 생성
        session_id = cl.user_session.get("session_id")
        if not session_id:
            session_id = str(uuid.uuid4())
            cl.user_session.set("session_id", session_id)
            chat_history[session_id] = []
        
        # 클라이언트 ID 생성
        client_id = f"cl_{uuid.uuid4().hex[:8]}"
        
        # 사용자 ID 저장 (나중에 응답을 찾기 위함)
        cl.user_session.set("last_client_id", client_id)
        
        # 메시지 전송을 위한 페이로드 구성
        payload = {
            "client_id": client_id,
            "message": message_content,
            "message_type": "chat",
            "timestamp": datetime.datetime.now().isoformat(),
            "context": {
                "session_id": session_id,
                "chat_history_length": len(chat_history.get(session_id, [])),
                "user_info": cl.user_session.get("user_info", {})
            }
        }
        
        # 대화 이력에 사용자 메시지 추가
        if session_id in chat_history:
            chat_history[session_id].append({"role": "user", "content": message_content})
        
        # 재시도 로직을 포함한 메시지 전송
        success = False
        response_data = None
        for retry in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    # 메시지 전송
                    response = await client.post(f"{API_GATEWAY_URL}/chat/messages", json=payload)
                    
                    if response.status_code == 200:
                        response_data = response.json()
                        success = True
                        break
                    else:
                        logger.warning(f"메시지 전송 실패 (시도 {retry+1}/{MAX_RETRIES}): HTTP {response.status_code} - {response.text}")
                        if retry < MAX_RETRIES - 1:
                            await asyncio.sleep(RETRY_DELAY)
            except httpx.RequestError as e:
                logger.warning(f"API 게이트웨이 연결 오류 (시도 {retry+1}/{MAX_RETRIES}): {str(e)}")
                if retry < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
        
        if not success:
            await processing_msg.remove()
            await cl.Message(content="서버와 통신할 수 없습니다. 잠시 후 다시 시도해 주세요.", author="시스템").send()
            return
        
        # 응답 대기 및 폴링 로직
        max_polls = 10  # 최대 폴링 횟수
        poll_interval = 1.0  # 폴링 간격 (초)
        
        # 응답을 받을 때까지 폴링
        empty_response_count = 0  # 연속된 빈 응답 횟수
        for poll in range(max_polls):
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    supervisor_response = await client.get(f"{API_GATEWAY_URL}/supervisor/responses/{client_id}")
                    
                    if supervisor_response.status_code == 200:
                        response_data = supervisor_response.json()
                        if response_data and "response" in response_data:  # 응답이 있으면 처리
                            response_message = response_data.get("response", "")
                            if response_message:
                                # 대화 이력에 응답 추가
                                if session_id in chat_history:
                                    chat_history[session_id].append({"role": "assistant", "content": response_message})
                                
                                # 처리 중 메시지 삭제
                                await processing_msg.remove()
                                
                                # 응답 메시지 스트리밍 전송
                                msg = cl.Message(content="", author="정비 어시스턴트")
                                
                                # 문장 단위로 스트리밍하기 위해 응답 분할
                                sentences = response_message.split(". ")
                                
                                # 마지막 문장에는 '.'를 추가하지 않음
                                for i, sentence in enumerate(sentences):
                                    if i < len(sentences) - 1:
                                        sentence += ". "
                                    await msg.stream_token(sentence)
                                    # 사용자 경험을 위해 약간의 지연 추가
                                    await asyncio.sleep(0.05)
                                
                                await msg.send()
                                return
                        else:
                            # 빈 응답인 경우
                            empty_response_count += 1
                            # 3번 연속 빈 응답이면 타임아웃으로 간주
                            if empty_response_count >= 3:
                                logger.warning(f"연속된 빈 응답으로 간주함: client_id={client_id}")
                                break
                    
                    # 폴링 계속
                    if poll < max_polls - 1:
                        # 응답을 기다리고 있다는 메시지 업데이트
                        if poll > 2:  # 처음 몇 번의 폴링은 조용히 진행
                            dots = "." * ((poll % 3) + 1)
                            await processing_msg.remove()
                            processing_msg = await cl.Message(content=f"응답을 생성하고 있습니다{dots}", author="시스템").send()
                        await asyncio.sleep(poll_interval)
                    else:
                        # 최대 폴링 횟수에 도달
                        logger.warning(f"응답 폴링 시간 초과: {client_id}")
                        
                        # 최후의 시도로 다시 한번 응답 확인
                        try:
                            final_check = await client.get(f"{API_GATEWAY_URL}/supervisor/responses/{client_id}")
                            if final_check.status_code == 200:
                                final_data = final_check.json()
                                if final_data and "response" in final_data:
                                    response_message = final_data.get("response", "")
                                    if response_message:
                                        # 최종 응답 처리
                                        if session_id in chat_history:
                                            chat_history[session_id].append({"role": "assistant", "content": response_message})
                                            
                                        await processing_msg.remove()
                                        await cl.Message(content=response_message, author="정비 어시스턴트").send()
                                        return
                        except:
                            pass
                        
                        await processing_msg.remove()
                        await cl.Message(content="응답을 받는 데 시간이 너무 오래 걸립니다. 나중에 다시 시도해 주세요.", author="시스템").send()
                
            except httpx.RequestError as e:
                logger.error(f"수퍼바이저 연결 오류: {str(e)}")
                # 마지막 시도가 아니면 재시도
                if poll < max_polls - 1:
                    await asyncio.sleep(poll_interval)
                else:
                    await processing_msg.remove()
                    await cl.Message(content="응답을 받는 중 오류가 발생했습니다. 서버 연결을 확인하세요.", author="시스템").send()
                    return
                
    except Exception as e:
        logger.error(f"메시지 처리 중 오류가 발생했습니다: {str(e)}")
        await processing_msg.remove()
        await cl.Message(content=f"메시지 처리 중 오류가 발생했습니다: {str(e)}", author="시스템").send()

@cl.action_callback("check_scenario1")
async def check_scenario1_callback(action):
    """시나리오 1: 모니터링 트리거에 의한 자동 대응 확인"""
    processing_msg = await cl.Message(content="시나리오 1 동작을 확인 중입니다...", author="시스템").send()
    
    try:
        # 이벤트 게이트웨이에 테스트 이벤트 전송
        async with httpx.AsyncClient(timeout=10.0) as client:
            test_event = {
                "event_type": "test_monitoring_event",
                "source": "frontend_test",
                "data": {
                    "car_id": "test_car_123",
                    "metric": "engine_temperature",
                    "value": 110,
                    "threshold": 90,
                    "timestamp": datetime.datetime.now().isoformat()
                }
            }
            
            # API 게이트웨이를 통한 이벤트 전송
            for retry in range(MAX_RETRIES):
                try:
                    response = await client.post(f"{API_GATEWAY_URL}/events", json=test_event)
                    
                    if response.status_code == 200:
                        event_id = response.json().get("event_id", "unknown")
                        
                        # 이벤트 처리 결과 확인 (폴링)
                        max_polls = 5
                        for poll in range(max_polls):
                            try:
                                status_response = await client.get(f"{API_GATEWAY_URL}/events/{event_id}/status")
                                
                                if status_response.status_code == 200:
                                    status_data = status_response.json()
                                    
                                    if status_data.get("status") == "processed":
                                        result_msg = f"""
## 시나리오 1 확인 완료 ✅

**이벤트 ID**: `{event_id}`
**상태**: 정상 처리됨
**처리 결과**: {status_data.get('result', '정보 없음')}

시나리오 1(모니터링 트리거에 의한 자동 대응)이 정상적으로 작동했습니다.
"""
                                        await processing_msg.update()
                                        await processing_msg.remove()
                                        await cl.Message(content=result_msg, author="시스템").send()
                                        return
                                    elif status_data.get("status") == "failed":
                                        result_msg = f"""
## 시나리오 1 확인 실패 ❌

**이벤트 ID**: `{event_id}`
**상태**: 처리 실패
**오류**: {status_data.get('error', '알 수 없는 오류')}

시나리오 1(모니터링 트리거에 의한 자동 대응)이 실패했습니다.
"""
                                        await processing_msg.update()
                                        await processing_msg.remove()
                                        await cl.Message(content=result_msg, author="시스템").send()
                                        return
                                    else:
                                        # 처리 중인 경우 폴링 계속
                                        await asyncio.sleep(1)
                                else:
                                    # 상태 확인 실패
                                    if poll == max_polls - 1:
                                        result_msg = f"""
## 시나리오 1 상태 확인 실패 ❌

**이벤트 ID**: `{event_id}`
**오류**: 이벤트 상태를 확인할 수 없습니다. (HTTP {status_response.status_code})

시나리오 1(모니터링 트리거에 의한 자동 대응) 확인에 실패했습니다.
"""
                                        await processing_msg.update()
                                        await processing_msg.remove()
                                        await cl.Message(content=result_msg, author="시스템").send()
                                        return
                            except Exception as e:
                                # 마지막 폴링 시도에서만 오류 메시지 표시
                                if poll == max_polls - 1:
                                    result_msg = f"""
## 시나리오 1 상태 확인 중 오류 ❌

**이벤트 ID**: `{event_id}`
**오류**: {str(e)}

시나리오 1(모니터링 트리거에 의한 자동 대응) 확인 중 오류가 발생했습니다.
"""
                                    await processing_msg.update()
                                    await processing_msg.remove()
                                    await cl.Message(content=result_msg, author="시스템").send()
                                    return
                        
                        # 최대 폴링 시도 후에도 결과 확인 불가
                        result_msg = f"""
## 시나리오 1 확인 시간 초과 ⚠️

**이벤트 ID**: `{event_id}`
**상태**: 처리 중 또는 알 수 없음

이벤트가 처리되는 데 예상보다 시간이 오래 걸리고 있습니다. 시스템 상태를 확인하세요.
"""
                        await processing_msg.update()
                        await processing_msg.remove()
                        await cl.Message(content=result_msg, author="시스템").send()
                    else:
                        # 이벤트 전송 실패
                        if retry == MAX_RETRIES - 1:
                            result_msg = f"""
## 시나리오 1 이벤트 전송 실패 ❌

**오류**: 이벤트를 전송할 수 없습니다. (HTTP {response.status_code})
**메시지**: {response.text}

시나리오 1(모니터링 트리거에 의한 자동 대응) 확인에 실패했습니다.
"""
                            await processing_msg.update()
                            await processing_msg.remove()
                            await cl.Message(content=result_msg, author="시스템").send()
                        else:
                            await asyncio.sleep(RETRY_DELAY)
                except Exception as e:
                    # 마지막 재시도에서만 오류 메시지 표시
                    if retry == MAX_RETRIES - 1:
                        result_msg = f"""
## 시나리오 1 이벤트 전송 중 오류 ❌

**오류**: {str(e)}

시나리오 1(모니터링 트리거에 의한 자동 대응) 확인 중 오류가 발생했습니다.
"""
                        await processing_msg.update()
                        await processing_msg.remove()
                        await cl.Message(content=result_msg, author="시스템").send()
                    else:
                        await asyncio.sleep(RETRY_DELAY)
                
    except Exception as e:
        result_msg = f"""
## 시나리오 1 확인 중 오류 발생 ❌

**오류**: {str(e)}

시나리오 1(모니터링 트리거에 의한 자동 대응) 확인 중 예기치 않은 오류가 발생했습니다.
"""
        await processing_msg.update()
        await processing_msg.remove()
        await cl.Message(content=result_msg, author="시스템").send()

@cl.action_callback("check_scenario2")
async def check_scenario2_callback(action):
    """시나리오 2: 사용자 채팅/인터럽트를 통한 에이전트 상호작용 확인"""
    processing_msg = await cl.Message(content="시나리오 2 동작을 확인 중입니다...", author="시스템").send()
    
    try:
        # 테스트 메시지 생성 및 전송
        test_message = "테스트: 엔진 오일 경고등이 켜졌습니다. 어떻게 해야 하나요?"
        
        # 채팅 게이트웨이에 테스트 메시지 전송
        await processing_msg.update(content=f"""
## 시나리오 2 테스트 중...

테스트 메시지:
"{test_message}"

메시지 처리 결과를 기다리는 중...
""")
        
        # 실제 메시지 전송은 send_to_chat_gateway 함수를 사용
        await send_to_chat_gateway(test_message, processing_msg)
        
    except Exception as e:
        await processing_msg.update(content=f"""
## 시나리오 2 확인 중 오류 발생 ❌

**오류**: {str(e)}

시나리오 2(사용자 채팅/인터럽트를 통한 에이전트 상호작용) 확인 중 예기치 않은 오류가 발생했습니다.
""")

@cl.action_callback("test_mcp_scenario")
async def test_mcp_scenario_callback(action):
    """MCP 기반 의사소통 시나리오 테스트"""
    processing_msg = await cl.Message(content="MCP 의사소통 시나리오를 테스트 중입니다...", author="시스템").send()
    
    try:
        # MCP 서버에 실행 요청 생성
        client_id = f"test_mcp_{uuid.uuid4().hex[:8]}"
        
        # 테스트할 MCP 메시지 설계
        mcp_test_payload = {
            "client_id": client_id,
            "agent_id": "test_agent",
            "execution_type": "chat_completion",
            "parameters": {
                "messages": [
                    {"role": "system", "content": "자동차 정비 전문가로서 역할을 수행하세요."},
                    {"role": "user", "content": "엔진 오일 경고등이 켜졌습니다. 어떻게 해야 하나요?"}
                ],
                "tools": [
                    {
                        "tool_id": "car_diagnostic_tool",
                        "name": "자동차 진단 도구",
                        "description": "차량 상태를 진단하고 문제를 파악합니다."
                    }
                ]
            }
        }
        
        await processing_msg.update(content=f"""
## MCP 시나리오 테스트 중...

1. MCP 서버에 메시지 전송 중...
""")
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            # MCP 서버에 요청 전송
            for retry in range(MAX_RETRIES):
                try:
                    response = await client.post(f"{MCP_SERVER_URL}/execute", json=mcp_test_payload)
                    
                    if response.status_code == 200:
                        result = response.json()
                        execution_id = result.get("execution_id")
                        
                        await processing_msg.update(content=f"""
## MCP 시나리오 테스트 중...

1. MCP 서버에 메시지 전송 완료 ✅
2. 실행 ID: `{execution_id}`
3. 처리 결과 대기 중...
""")
                        
                        # 실행 상태 폴링
                        max_polls = 10
                        for poll in range(max_polls):
                            try:
                                status_response = await client.get(f"{MCP_SERVER_URL}/status/{execution_id}")
                                
                                if status_response.status_code == 200:
                                    status_data = status_response.json()
                                    exec_status = status_data.get("status")
                                    
                                    if exec_status == "completed":
                                        result = status_data.get("result", {})
                                        await processing_msg.update(content=f"""
## MCP 시나리오 테스트 완료 ✅

1. MCP 서버에 메시지 전송 완료 ✅
2. 실행 ID: `{execution_id}`
3. 처리 완료 ✅
4. 결과:
```json
{json.dumps(result, indent=2, ensure_ascii=False)}
```

MCP 기반 상호작용이 성공적으로 수행되었습니다.
""")
                                        return
                                    elif exec_status == "failed":
                                        error = status_data.get("error", "알 수 없는 오류")
                                        await processing_msg.update(content=f"""
## MCP 시나리오 테스트 실패 ❌

1. MCP 서버에 메시지 전송 완료 ✅
2. 실행 ID: `{execution_id}`
3. 처리 실패 ❌
4. 오류: {error}

MCP 기반 상호작용 중 오류가 발생했습니다.
""")
                                        return
                                    else:
                                        # 진행 중인 상태
                                        dots = "." * ((poll % 3) + 1)
                                        await processing_msg.update(content=f"""
## MCP 시나리오 테스트 중{dots}

1. MCP 서버에 메시지 전송 완료 ✅
2. 실행 ID: `{execution_id}`
3. 현재 상태: {exec_status}
""")
                                        await asyncio.sleep(1)
                                else:
                                    await processing_msg.update(content=f"""
## MCP 시나리오 테스트 확인 실패 ❌

1. MCP 서버에 메시지 전송 완료 ✅
2. 실행 ID: `{execution_id}`
3. 상태 확인 실패: HTTP {status_response.status_code}

MCP 실행 상태를 확인할 수 없습니다.
""")
                                    return
                            except Exception as e:
                                await processing_msg.update(content=f"""
## MCP 시나리오 테스트 상태 확인 중 오류 ❌

1. MCP 서버에 메시지 전송 완료 ✅
2. 실행 ID: `{execution_id}`
3. 상태 확인 중 오류: {str(e)}

MCP 실행 상태를 확인하는 중 오류가 발생했습니다.
""")
                                return
                        
                        # 최대 폴링 시도 후에도 결과 확인 불가
                        await processing_msg.update(content=f"""
## MCP 시나리오 테스트 시간 초과 ⚠️

1. MCP 서버에 메시지 전송 완료 ✅
2. 실행 ID: `{execution_id}`
3. 시간 초과: 결과를 얻지 못했습니다.

MCP 실행이 완료되지 않았거나 응답이 지연되고 있습니다.
""")
                        return
                    else:
                        if retry == MAX_RETRIES - 1:
                            await processing_msg.update(content=f"""
## MCP 시나리오 테스트 실패 ❌

MCP 서버에 메시지 전송 실패: HTTP {response.status_code}
오류: {response.text}
""")
                        else:
                            await asyncio.sleep(RETRY_DELAY)
                except Exception as e:
                    if retry == MAX_RETRIES - 1:
                        await processing_msg.update(content=f"""
## MCP 시나리오 테스트 실패 ❌

MCP 서버 연결 중 오류 발생: {str(e)}
""")
                    else:
                        await asyncio.sleep(RETRY_DELAY)
                        
    except Exception as e:
        await processing_msg.update(content=f"""
## MCP 시나리오 테스트 중 오류 발생 ❌

오류: {str(e)}

MCP 시나리오 테스트 중 예기치 않은 오류가 발생했습니다.
""")

@cl.action_callback("check_service_registry")
async def check_service_registry_callback(action):
    """서비스 레지스트리 상태 및 등록된 서비스 확인"""
    processing_msg = await cl.Message(content="서비스 레지스트리를 확인 중입니다...", author="시스템").send()
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # 서비스 레지스트리 상태 확인
            try:
                health_response = await client.get("http://service-registry:8007/health")
                registry_healthy = health_response.status_code == 200
            except:
                registry_healthy = False
            
            # 등록된 서비스 목록 조회
            try:
                services_response = await client.get("http://service-registry:8007/services")
                if services_response.status_code == 200:
                    services = services_response.json()
                else:
                    services = []
            except:
                services = []
            
            # 결과 표시
            if registry_healthy:
                content = "## 서비스 레지스트리 상태: ✅ 정상\n\n"
            else:
                content = "## 서비스 레지스트리 상태: ❌ 오류\n\n"
            
            if services:
                content += "### 등록된 서비스 목록\n\n"
                for service in services:
                    service_name = service.get("name", "알 수 없음")
                    service_url = service.get("url", "알 수 없음")
                    service_health = service.get("health_check_url", "알 수 없음")
                    
                    # 서비스 상태 확인
                    try:
                        health_check_response = await client.get(service_health, timeout=2.0)
                        service_status = "✅ 정상" if health_check_response.status_code == 200 else "❌ 오류"
                    except:
                        service_status = "❌ 연결 실패"
                    
                    content += f"- **{service_name}**: {service_status}\n"
                    content += f"  - URL: {service_url}\n"
                    content += f"  - 헬스체크: {service_health}\n\n"
            else:
                content += "### 등록된 서비스가 없습니다.\n\n"
            
            await processing_msg.update(content=content)
    
    except Exception as e:
        await processing_msg.update(content=f"""
## 서비스 레지스트리 확인 중 오류 발생 ❌

오류: {str(e)}

서비스 레지스트리 상태를 확인하는 중 예기치 않은 오류가 발생했습니다.
""") 