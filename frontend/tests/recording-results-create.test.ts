import { afterEach, describe, expect, it, vi } from 'vite-plus/test'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, toValue } from 'vue'
import { installColada } from './colada'

const sdk = vi.hoisted(() => ({
  recordingAiResults: vi.fn(),
  recordingsEvents: vi.fn(),
  recordingAiCreateResults: vi.fn(),
}))
vi.mock('~/shared/api/generated', async (original) => ({ ...(await original()), ...sdk }))

const { useRecordingResults } = await import('../app/features/recording/composables/useRecordingDetail')

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('creating summaries', () => {
  it('succeeds even when the list refetch afterwards fails (a realtime update cancelled it)', async () => {
    const plugins = installColada()
    vi.stubGlobal('toValue', toValue)
    sdk.recordingAiResults
      .mockResolvedValueOnce({ data: [] })
      .mockRejectedValue(new DOMException('aborted', 'AbortError'))
    sdk.recordingsEvents.mockRejectedValue(new DOMException('aborted', 'AbortError'))
    sdk.recordingAiCreateResults.mockResolvedValue({ data: [{ id: 'r1', status: 'queued' }] })

    let results!: ReturnType<typeof useRecordingResults>
    mount(
      defineComponent({
        setup() {
          results = useRecordingResults('rec-1')
          return () => null
        },
      }),
      { global: { plugins: plugins as never } },
    )
    await flushPromises()

    await expect(
      results.create.mutateAsync({ template_ids: [], custom_prompt: 'Кратко', model: null }),
    ).resolves.toEqual([{ id: 'r1', status: 'queued' }])
    await flushPromises()
    expect(sdk.recordingAiCreateResults).toHaveBeenCalledOnce()
  })
})
