/**
 * A2A MCP API 클라이언트
 * 이 파일은 일렉트론 UI를 대체하여 API를 테스트하는 헤드리스 클라이언트입니다.
 */

const axios = require('axios');

// 환경 변수에서 API URL 가져오기
const API_SERVER_URL = process.env.API_SERVER_URL || 'http://localhost:8000';
const EVENT_GATEWAY_URL = process.env.EVENT_GATEWAY_URL || 'http://localhost:8010';
const CHAT_GATEWAY_URL = process.env.CHAT_GATEWAY_URL || 'http://localhost:8020';
const SUPERVISOR_URL = process.env.SUPERVISOR_URL || 'http://localhost:8030';

console.log('==================================================');
console.log('A2A MCP 자동차 정비 서비스 API 테스트 클라이언트');
console.log('==================================================');
console.log('API 서버 URL:', API_SERVER_URL);
console.log('이벤트 게이트웨이 URL:', EVENT_GATEWAY_URL);
console.log('채팅 게이트웨이 URL:', CHAT_GATEWAY_URL);
console.log('슈퍼바이저 URL:', SUPERVISOR_URL);
console.log('==================================================');

// API 테스트 함수 정의
async function runApiTests() {
  try {
    console.log('API 서버 연결 테스트 중...');
    
    // 1. 에이전트 목록 가져오기
    console.log('\n[테스트 1] 에이전트 목록 가져오기');
    const agentsResponse = await axios.get(`${API_SERVER_URL}/agents`);
    console.log('에이전트 목록 응답:', JSON.stringify(agentsResponse.data, null, 2));
    
    // 2. 새 작업 생성하기
    console.log('\n[테스트 2] 새 작업 생성하기');
    const taskData = {
      customer_id: `customer_${Date.now()}`,
      vehicle_id: `VIN_${Date.now()}`,
      vehicle_info: {
        make: '현대',
        model: '소나타',
        year: 2020
      },
      description: '테스트 작업: 차에서 덜컹거리는 소리가 나고 엔진 경고등이 켜졌습니다.',
      symptoms: ['엔진 소음', '엔진 경고등']
    };
    
    const taskResponse = await axios.post(`${API_SERVER_URL}/tasks`, taskData);
    console.log('작업 생성 응답:', JSON.stringify(taskResponse.data, null, 2));
    const taskId = taskResponse.data.task_id;
    
    // 3. 작업 상세 정보 가져오기
    console.log(`\n[테스트 3] 작업 상세 정보 가져오기 (ID: ${taskId})`);
    await new Promise(resolve => setTimeout(resolve, 2000)); // 2초 대기
    
    const taskDetailResponse = await axios.get(`${API_SERVER_URL}/tasks/${taskId}`);
    console.log('작업 상세 정보 응답:', JSON.stringify(taskDetailResponse.data, null, 2));
    
    // 4. 부품 주문하기
    console.log('\n[테스트 4] 부품 주문하기');
    const orderData = {
      task_id: taskId,
      part_number: '12345',
      quantity: 2
    };
    
    try {
      const orderResponse = await axios.post(`${API_SERVER_URL}/parts/order`, orderData);
      console.log('부품 주문 응답:', JSON.stringify(orderResponse.data, null, 2));
    } catch (error) {
      console.log('부품 주문 실패:', error.message);
      if (error.response) {
        console.log('응답 데이터:', JSON.stringify(error.response.data, null, 2));
      }
    }
    
    // 5. 슈퍼바이저 연결 테스트
    console.log('\n[테스트 5] 슈퍼바이저 연결 테스트');
    try {
      const supervisorResponse = await axios.get(`${SUPERVISOR_URL}`);
      console.log('슈퍼바이저 응답:', supervisorResponse.status);
      console.log('슈퍼바이저 데이터:', JSON.stringify(supervisorResponse.data, null, 2));
    } catch (error) {
      console.log('슈퍼바이저 연결 실패:', error.message);
    }
    
    console.log('\n모든 API 테스트가 완료되었습니다.');
    
  } catch (error) {
    console.error('API 테스트 중 오류 발생:', error.message);
    if (error.response) {
      console.error('응답 상태:', error.response.status);
      console.error('응답 데이터:', JSON.stringify(error.response.data, null, 2));
    }
  }
}

// 15초마다 API 테스트 실행
console.log('API 테스트를 15초마다 실행합니다...');
runApiTests();
setInterval(runApiTests, 15000);

// 종료 시그널 처리
process.on('SIGINT', () => {
  console.log('API 테스트 클라이언트를 종료합니다.');
  process.exit(0);
});

process.on('SIGTERM', () => {
  console.log('API 테스트 클라이언트를 종료합니다.');
  process.exit(0);
}); 