import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useLibraryStore } from '../src/stores/library'
import { uploadDocument } from '../src/api/knowledgeBase'
vi.mock('../src/api/knowledgeBase',()=>({
  listDocuments:vi.fn(),getDocumentChunks:vi.fn(),getIngestJob:vi.fn(),getKnowledgeOverview:vi.fn(),
  syncKnowledge:vi.fn(),deleteDocument:vi.fn(),uploadDocument:vi.fn(),checkDocument:vi.fn(),
}))
beforeEach(()=>{setActivePinia(createPinia());vi.clearAllMocks()})
describe('upload account boundary',()=>{
  it('does not start the next queued upload or poll old files after account reset',async()=>{
    let resolve
    uploadDocument.mockImplementationOnce(()=>new Promise(done=>{resolve=done}))
    const store=useLibraryStore()
    const pending=store.uploadFiles([{name:'first.txt',size:1},{name:'second.txt',size:1}])
    expect(uploadDocument).toHaveBeenCalledTimes(1)
    store.reset()
    resolve({file_md5:'old-file'})
    await pending
    expect(uploadDocument).toHaveBeenCalledTimes(1)
    expect(store.uploads).toEqual([])
  })
})
