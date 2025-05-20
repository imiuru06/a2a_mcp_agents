const { contextBridge, ipcRenderer } = require('electron');

// 렌더러 프로세스에 API 노출
contextBridge.exposeInMainWorld('electronAPI', {
  // 에이전트 관련 API
  getAgents: () => ipcRenderer.invoke('get-agents'),
  getAgent: (agentId) => ipcRenderer.invoke('get-agent', agentId),
  
  // 작업 관련 API
  createTask: (taskData) => ipcRenderer.invoke('create-task', taskData),
  getTask: (taskId) => ipcRenderer.invoke('get-task', taskId),
  
  // 부품 주문 API
  orderParts: (orderData) => ipcRenderer.invoke('order-parts', orderData),
  
  // 설정 관련 API
  setApiUrl: (url) => ipcRenderer.invoke('set-api-url', url),
  getApiUrl: () => ipcRenderer.invoke('get-api-url')
}); 