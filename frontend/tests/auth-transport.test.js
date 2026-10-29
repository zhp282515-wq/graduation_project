import { afterEach, describe, expect, it, vi } from 'vitest'
import { request, setCsrfToken, invalidateRequests, finishResponse } from '../src/api/http'

afterEach(() => { invalidateRequests();setCsrfToken('');vi.unstubAllGlobals() })

describe('authenticated transport', () => {
  it('uses same-origin cookies and CSRF headers without a spoofable user id', async () => {
    const fetcher=vi.fn().mockResolvedValue(new Response('{"ok":true}',{status:200}))
    vi.stubGlobal('fetch',fetcher);setCsrfToken('csrf-example')
    await request('/api/sessions',{method:'POST',body:{}})
    const options=fetcher.mock.calls[0][1]
    expect(options.credentials).toBe('same-origin')
    expect(options.headers['X-CSRF-Token']).toBe('csrf-example')
    expect(options.headers).not.toHaveProperty('x-user-id')
  })

  it('discards a response from an account that has been cleared even if fetch ignores abort', async () => {
    let resolve
    vi.stubGlobal('fetch',vi.fn(() => new Promise((done) => {resolve=done})))
    const pending=request('/api/memories')
    invalidateRequests()
    resolve(new Response('[{"content":"old private memory"}]',{status:200}))
    await expect(pending).rejects.toMatchObject({name:'AbortError'})
  })

  it('aborts an ongoing SSE body when the account changes', async () => {
    let signal
    vi.stubGlobal('fetch',vi.fn((_,options) => {signal=options.signal;return Promise.resolve(new Response('data: {}\n\n'))}))
    const response=await request('/api/chat',{method:'POST',raw:true})
    expect(signal.aborted).toBe(false)
    invalidateRequests();expect(signal.aborted).toBe(true)
    finishResponse(response)
  })
})
