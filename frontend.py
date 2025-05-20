#!/usr/bin/env python3
"""
A2A 및 MCP 에이전트 서비스를 위한 웹 인터페이스
Streamlit을 사용하여 구현된 단순한 프론트엔드
"""

import streamlit as st
import requests
import json
import time
import pandas as pd
from datetime import datetime

# API 서비스 URL
API_URL = "http://localhost:8000"

# 페이지 설정
st.set_page_config(
    page_title="자동차 정비 에이전트 서비스",
    page_icon="🚗",
    layout="wide"
)

# 스타일 설정
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1E6091;
        margin-bottom: 1rem;
    }
    .section-header {
        font-size: 1.8rem;
        font-weight: bold;
        color: #1E6091;
        margin-top: 2rem;
        margin-bottom: 1rem;
    }
    .card {
        background-color: #f9f9f9;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }
    .agent-card {
        background-color: #e6f3ff;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 15px;
    }
    .status-completed {
        color: #008800;
        font-weight: bold;
    }
    .status-in-progress {
        color: #FF8800;
        font-weight: bold;
    }
    .status-pending {
        color: #0088FF;
        font-weight: bold;
    }
    .status-failed {
        color: #FF0000;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# 세션 상태 초기화
if 'tasks' not in st.session_state:
    st.session_state.tasks = {}  # 작업 ID를 키로 하는 작업 정보 딕셔너리

if 'selected_task' not in st.session_state:
    st.session_state.selected_task = None

if 'agents' not in st.session_state:
    st.session_state.agents = []
    # 에이전트 정보 가져오기
    try:
        response = requests.get(f"{API_URL}/agents")
        if response.status_code == 200:
            st.session_state.agents = response.json()
    except Exception as e:
        st.error(f"에이전트 정보를 가져오는 중 오류 발생: {str(e)}")

# 유틸리티 함수
def get_status_class(status):
    """상태에 따른 CSS 클래스 반환"""
    status_mapping = {
        "completed": "status-completed",
        "in_progress": "status-in-progress",
        "pending": "status-pending",
        "failed": "status-failed"
    }
    return status_mapping.get(status, "")

def format_timestamp(timestamp_str):
    """타임스탬프 형식화"""
    try:
        dt = datetime.fromisoformat(timestamp_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return timestamp_str

# 헤더
st.markdown('<div class="main-header">🚗 자동차 정비 에이전트 서비스</div>', unsafe_allow_html=True)
st.markdown("A2A와 MCP 프로토콜을 활용한 자동차 정비 시스템 대시보드")

# 탭 설정
tab1, tab2, tab3 = st.tabs(["새 작업 등록", "작업 현황", "에이전트 정보"])

# 탭 1: 새 작업 등록
with tab1:
    st.markdown('<div class="section-header">새 차량 문제 등록</div>', unsafe_allow_html=True)
    
    with st.form("repair_request_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            customer_id = st.text_input("고객 ID", value="customer_" + str(int(time.time())))
            vehicle_id = st.text_input("차량 ID", value="VIN_" + str(int(time.time())))
            
            # 증상 선택 (다중 선택 가능)
            symptoms = st.multiselect(
                "증상 선택",
                options=[
                    "엔진 소음", "엔진 경고등", "과열", "시동 문제", "제동 문제",
                    "변속 문제", "연비 저하", "배기가스 문제", "전기 시스템 문제", "기타"
                ],
                default=["엔진 소음"]
            )
        
        with col2:
            make = st.selectbox("제조사", ["현대", "기아", "BMW", "벤츠", "아우디", "도요타", "혼다", "포드", "기타"])
            model = st.text_input("모델", value="소나타")
            year = st.number_input("연식", min_value=1990, max_value=2025, value=2020)
            
            description = st.text_area("문제 상세 설명", height=120, 
                                      value="차에서 덜컹거리는 소리가 나고 엔진 경고등이 켜졌습니다.")
        
        submit_button = st.form_submit_button(label="작업 등록")
        
    if submit_button:
        with st.spinner("작업을 등록 중입니다..."):
            try:
                # API 요청 데이터 준비
                request_data = {
                    "customer_id": customer_id,
                    "vehicle_id": vehicle_id,
                    "vehicle_info": {
                        "make": make,
                        "model": model,
                        "year": year
                    },
                    "description": description,
                    "symptoms": symptoms
                }
                
                # API 호출
                response = requests.post(f"{API_URL}/tasks", json=request_data)
                
                if response.status_code == 200:
                    result = response.json()
                    st.success(f"작업이 성공적으로 등록되었습니다! 작업 ID: {result['task_id']}")
                    
                    # 작업 정보 가져오기
                    task_response = requests.get(f"{API_URL}/tasks/{result['task_id']}")
                    if task_response.status_code == 200:
                        task_data = task_response.json()
                        st.session_state.tasks[result['task_id']] = task_data
                        st.session_state.selected_task = result['task_id']
                    
                    # 작업 현황 탭으로 자동 전환
                    st.experimental_rerun()
                else:
                    st.error(f"작업 등록 실패: {response.text}")
            except Exception as e:
                st.error(f"오류 발생: {str(e)}")

# 탭 2: 작업 현황
with tab2:
    st.markdown('<div class="section-header">작업 현황</div>', unsafe_allow_html=True)
    
    # 작업 목록 새로고침 버튼
    if st.button("작업 목록 새로고침"):
        try:
            # 모든 작업에 대해 최신 정보 가져오기
            updated_tasks = {}
            for task_id in st.session_state.tasks.keys():
                response = requests.get(f"{API_URL}/tasks/{task_id}")
                if response.status_code == 200:
                    updated_tasks[task_id] = response.json()
            
            if updated_tasks:
                st.session_state.tasks = updated_tasks
                st.success("작업 목록이 새로고침되었습니다.")
            else:
                st.info("새로고침할 작업이 없습니다.")
        except Exception as e:
            st.error(f"작업 목록 새로고침 중 오류 발생: {str(e)}")
    
    # 작업이 있는 경우 테이블로 표시
    if st.session_state.tasks:
        task_data = []
        for task_id, task in st.session_state.tasks.items():
            task_data.append({
                "작업 ID": task_id,
                "제목": task["title"],
                "상태": task["status"],
                "담당자": task["assigned_to"] or "-",
                "생성일": format_timestamp(task["created_at"])
            })
        
        df = pd.DataFrame(task_data)
        st.dataframe(df, use_container_width=True)
        
        # 작업 ID 선택 드롭다운
        selected_task_id = st.selectbox(
            "작업 상세 정보 조회",
            options=list(st.session_state.tasks.keys()),
            format_func=lambda x: f"{x} - {st.session_state.tasks[x]['title']}",
            index=list(st.session_state.tasks.keys()).index(st.session_state.selected_task) if st.session_state.selected_task in st.session_state.tasks else 0
        )
        
        st.session_state.selected_task = selected_task_id
        
        # 선택한 작업 상세 정보 표시
        if selected_task_id:
            task = st.session_state.tasks[selected_task_id]
            
            st.markdown(f"<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"### {task['title']}")
            st.markdown(f"**상태:** <span class='{get_status_class(task['status'])}'>{task['status']}</span>", unsafe_allow_html=True)
            st.markdown(f"**담당자:** {task['assigned_to'] or '-'}")
            st.markdown(f"**생성일:** {format_timestamp(task['created_at'])}")
            
            # 작업 기록 표시
            if task['history']:
                st.markdown("### 작업 기록")
                for entry in task['history']:
                    st.markdown(f"**{entry['agent_id']}:** {entry['message']}")
            
            # 부품 주문 폼 (작업이 진행 중일 때만 표시)
            if task['status'] == 'in_progress' or task['status'] == 'pending':
                st.markdown("### 부품 주문")
                with st.form(f"order_parts_form_{selected_task_id}"):
                    part_number = st.selectbox(
                        "부품 번호",
                        options=["12345", "12346", "12347", "12348"],
                        format_func=lambda x: {
                            "12345": "12345 - 스파크 플러그",
                            "12346": "12346 - 에어 필터",
                            "12347": "12347 - 연료 인젝터",
                            "12348": "12348 - 산소 센서"
                        }.get(x, x)
                    )
                    quantity = st.number_input("수량", min_value=1, max_value=10, value=1)
                    
                    order_button = st.form_submit_button("부품 주문")
                
                if order_button:
                    try:
                        order_data = {
                            "task_id": selected_task_id,
                            "part_number": part_number,
                            "quantity": quantity
                        }
                        
                        response = requests.post(f"{API_URL}/parts/order", json=order_data)
                        
                        if response.status_code == 200:
                            result = response.json()
                            st.success(f"부품 주문 성공! 주문 ID: {result['order_id']}")
                            
                            # 작업 정보 새로고침
                            task_response = requests.get(f"{API_URL}/tasks/{selected_task_id}")
                            if task_response.status_code == 200:
                                st.session_state.tasks[selected_task_id] = task_response.json()
                                st.experimental_rerun()
                        else:
                            st.error(f"부품 주문 실패: {response.text}")
                    except Exception as e:
                        st.error(f"부품 주문 중 오류 발생: {str(e)}")
            
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("등록된 작업이 없습니다. '새 작업 등록' 탭에서 작업을 등록해주세요.")

# 탭 3: 에이전트 정보
with tab3:
    st.markdown('<div class="section-header">에이전트 정보</div>', unsafe_allow_html=True)
    
    if st.button("에이전트 정보 새로고침"):
        try:
            response = requests.get(f"{API_URL}/agents")
            if response.status_code == 200:
                st.session_state.agents = response.json()
                st.success("에이전트 정보가 새로고침되었습니다.")
        except Exception as e:
            st.error(f"에이전트 정보 새로고침 중 오류 발생: {str(e)}")
    
    if st.session_state.agents:
        for agent in st.session_state.agents:
            with st.container():
                st.markdown(f"<div class='agent-card'>", unsafe_allow_html=True)
                st.markdown(f"### {agent['name']} ({agent['agent_id']})")
                st.markdown(f"**설명:** {agent['description']}")
                
                # 기술 목록 표시
                st.markdown("**기술:**")
                for skill in agent['skills']:
                    st.markdown(f"- {skill}")
                
                # 지원하는 모달리티 표시
                st.markdown(f"**지원 모달리티:** {', '.join(agent['supported_modalities'])}")
                st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("에이전트 정보를 불러올 수 없습니다.")

# 페이지 하단 정보
st.markdown("---")
st.markdown("© 2025 자동차 정비 에이전트 서비스 | A2A 및 MCP 프로토콜 기반")

# 자동 업데이트를 위한 5초마다 상태 갱신 (실제로는 WebSocket을 사용하는 것이 더 효율적)
if st.session_state.tasks:
    time.sleep(5)
    st.experimental_rerun() 