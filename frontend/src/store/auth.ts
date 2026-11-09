import { defineStore } from 'pinia'
import { api, setUnauthorizedHandler } from '../api'

export interface Me {
  id: number
  phone: string
  nickname: string
  is_admin: boolean
  merchant_status: string | null
  rider_status: string | null
  rider_working_status?: string | null
  seats?: string[]
}

export const useAuth = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('sanshi_token') || '',
    me: JSON.parse(localStorage.getItem('sanshi_me') || 'null') as Me | null,
  }),
  getters: {
    isLogin: (s) => !!s.token,
    isMerchant: (s) => s.me?.merchant_status === 'ACTIVE',
    isRider: (s) => s.me?.rider_status === 'ACTIVE',
    isAdmin: (s) => !!s.me?.is_admin,
    hasSeat: (s) => (s.me?.seats?.length ?? 0) > 0,
  },
  actions: {
    setAuth(token: string, user: any) {
      this.token = token
      this.me = user
      localStorage.setItem('sanshi_token', token)
      localStorage.setItem('sanshi_me', JSON.stringify(user))
    },
    async refresh() {
      if (!this.token) return
      try {
        this.me = await api.get('/auth/me')
        localStorage.setItem('sanshi_me', JSON.stringify(this.me))
      } catch {
        this.logout()
      }
    },
    logout() {
      this.token = ''
      this.me = null
      localStorage.removeItem('sanshi_token')
      localStorage.removeItem('sanshi_me')
    },
  },
})

setUnauthorizedHandler(() => useAuth().logout())
