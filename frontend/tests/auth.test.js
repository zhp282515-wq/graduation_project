import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../src/stores/auth'
import { useConversationStore } from '../src/stores/conversations'
import { useLibraryStore } from '../src/stores/library'
import { useMemoryStore } from '../src/stores/memory'
import { useAtlasStore } from '../src/stores/atlas'
import { getIdentity, signIn, signUp, signOut } from '../src/api/auth'

vi.mock('../src/api/auth', () => ({ getIdentity:vi.fn(),signIn:vi.fn(),signUp:vi.fn(),signOut:vi.fn() }))
const identity = (role='user') => ({ user:{ id:'new-user',username:'alice',role,must_change_password:false },csrf_token:'csrf-fixture' })

beforeEach(() => { setActivePinia(createPinia());vi.clearAllMocks() })

describe('authentication lifecycle', () => {
  it('coalesces identity restoration and derives administrator access from the response', async () => {
    let resolve
    getIdentity.mockImplementation(() => new Promise((done) => { resolve=done }))
    const auth=useAuthStore()
    const a=auth.restore(),b=auth.restore()
    expect(getIdentity).toHaveBeenCalledTimes(1)
    resolve(identity('admin'));await Promise.all([a,b])
    expect(auth.ready).toBe(true);expect(auth.isAdmin).toBe(true)
  })

  it('allows anonymous entry but keeps network failures retryable', async () => {
    const auth=useAuthStore()
    getIdentity.mockRejectedValueOnce({status:503})
    await expect(auth.restore()).rejects.toMatchObject({status:503})
    expect(auth.ready).toBe(false)
    getIdentity.mockRejectedValueOnce({status:401})
    await auth.restore()
    expect(auth.ready).toBe(true);expect(auth.user).toBeNull()
  })

  it('clears personal contents, document caches and graph filters before switching accounts', async () => {
    const conversation=useConversationStore(),library=useLibraryStore(),memory=useMemoryStore(),atlas=useAtlasStore()
    conversation.turns=[{key:'private',userText:'private question'}]
    conversation.sessions=[{id:'private-session'}]
    library.items=[{file_name:'管理员文档'}];library.document={file_name:'管理员文档'}
    memory.items=[{content:'私人记忆'}];memory.draft='未保存的私人记忆'
    atlas.points=[{text:'私人片段'}];atlas.query='私人查询';atlas.docFilter='private-doc'
    signIn.mockResolvedValue(identity())
    await useAuthStore().authenticate('login',{username:'alice',password:'password-fixture'})
    expect(conversation.turns).toEqual([]);expect(conversation.sessions).toEqual([])
    expect(library.items).toEqual([]);expect(library.document).toBeNull()
    expect(memory.items).toEqual([]);expect(memory.draft).toBe('')
    expect(atlas.points).toEqual([]);expect(atlas.query).toBe('');expect(atlas.docFilter).toBe('')
    expect(useAuthStore().isAdmin).toBe(false)
  })

  it('uses the registration endpoint and removes identity after logout', async () => {
    signUp.mockResolvedValue(identity());signOut.mockResolvedValue({ok:true})
    const auth=useAuthStore()
    await auth.authenticate('register',{username:'alice',password:'password-fixture'})
    expect(signUp).toHaveBeenCalledOnce();expect(signIn).not.toHaveBeenCalled()
    await auth.logout();expect(auth.user).toBeNull()
  })

  it('keeps the current identity and reports a failed server logout so the user can retry', async () => {
    signIn.mockResolvedValue(identity());signOut.mockRejectedValue({status:503,message:'服务暂不可用'})
    const auth=useAuthStore()
    await auth.authenticate('login',{username:'alice',password:'password-fixture'})
    await expect(auth.logout()).rejects.toMatchObject({status:503})
    expect(auth.user.id).toBe('new-user')
  })
})
