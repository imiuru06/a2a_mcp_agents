const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const axios = require('axios');
const Store = require('electron-store');

// 설정 저장소 초기화
const store = new Store();

// API 서비스 URL
const API_URL = store.get('apiUrl') || 'http://localhost:8000';

// 개발 모드 확인
const isDev = process.env.NODE_ENV === 'development';

// 메인 윈도우 객체
let mainWindow;

// 헤드리스 모드 확인 (디스플레이가 없는 환경)
const isHeadless = !process.env.DISPLAY;

// 애플리케이션 준비 완료 시 실행
app.whenReady().then(() => {
  // 헤드리스 모드인 경우 콘솔에 메시지 출력
  if (isHeadless) {
    console.log('Electron 앱이 헤드리스 모드로 실행됩니다.');
    console.log('서버 API 연결 테스트를 시작합니다...');
    testAPIConnection().then(() => {
      app.quit();
    });
  } else {
    createWindow();

    // macOS에서 모든 창이 닫힌 후 앱 아이콘을 클릭하면 새 창 생성
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
      }
    });
  }
});

// 모든 창이 닫히면 앱 종료 (Windows 및 Linux)
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// API 연결 테스트 함수
async function testAPIConnection() {
  try {
    console.log(`API 서버 접속 테스트 중: ${API_URL}`);
    const response = await axios.get(`${API_URL}/agents`);
    console.log('API 연결 성공! 에이전트 정보:');
    console.log(response.data);
    return response.data;
  } catch (error) {
    console.error('API 연결 실패:', error.message);
    return { error: error.message };
  }
}

// 메인 윈도우 생성 함수
function createWindow() {
  // 헤드리스 모드에서는 윈도우 생성 건너뛰기
  if (isHeadless) {
    console.log('헤드리스 모드에서는 윈도우를 생성하지 않습니다.');
    return;
  }
  
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: false, // 보안을 위해 false로 설정
      contextIsolation: true, // 보안을 위해 true로 설정
      preload: path.join(__dirname, 'preload.js') // 프리로드 스크립트 설정
    },
    icon: path.join(__dirname, 'assets/icon.png')
  });

  // 개발 모드에서는 개발 서버 URL 로드, 아니면 로컬 HTML 파일 로드
  if (isDev) {
    mainWindow.loadFile(path.join(__dirname, 'renderer/index.html'));
    mainWindow.webContents.openDevTools(); // 개발 도구 열기
  } else {
    mainWindow.loadFile(path.join(__dirname, 'renderer/index.html'));
  }
}

// IPC 이벤트 핸들러 설정

// 에이전트 목록 요청
ipcMain.handle('get-agents', async () => {
  try {
    const response = await axios.get(`${API_URL}/agents`);
    return response.data;
  } catch (error) {
    console.error('에이전트 목록 요청 실패:', error);
    return { error: error.message };
  }
});

// 작업 생성 요청
ipcMain.handle('create-task', async (event, taskData) => {
  try {
    const response = await axios.post(`${API_URL}/tasks`, taskData);
    return response.data;
  } catch (error) {
    console.error('작업 생성 요청 실패:', error);
    return { error: error.message };
  }
});

// 작업 상태 요청
ipcMain.handle('get-task', async (event, taskId) => {
  try {
    const response = await axios.get(`${API_URL}/tasks/${taskId}`);
    return response.data;
  } catch (error) {
    console.error('작업 상태 요청 실패:', error);
    return { error: error.message };
  }
});

// 부품 주문 요청
ipcMain.handle('order-parts', async (event, orderData) => {
  try {
    const response = await axios.post(`${API_URL}/parts/order`, orderData);
    return response.data;
  } catch (error) {
    console.error('부품 주문 요청 실패:', error);
    return { error: error.message };
  }
});

// API URL 설정 변경
ipcMain.handle('set-api-url', (event, url) => {
  store.set('apiUrl', url);
  return { success: true };
});

// API URL 가져오기
ipcMain.handle('get-api-url', () => {
  return store.get('apiUrl') || API_URL;
}); 