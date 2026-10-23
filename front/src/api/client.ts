import axios from 'axios'
import { useUserStore } from '../stores/useUserStore'

export const JWT_KEY = 'jwt_token'

const client = axios.create({
  baseURL: '',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem(JWT_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body && typeof body.code === 'number' && body.code !== 200) {
      return Promise.reject(new Error(typeof body.message === 'string' ? body.message : '请求失败'))
    }
    return response
  },
  (error) => {
    if (error.response?.status === 401) {
      useUserStore.getState().logout()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default client
