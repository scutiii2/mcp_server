import { describe, expect, it } from 'vitest'
import { friendlyError, messageOf } from './messages'

describe('messages', () => {
  it('messageOf reads Error messages and stringifies the rest', () => {
    expect(messageOf(new Error('boom'))).toBe('boom')
    expect(messageOf('plain')).toBe('plain')
  })

  it('friendlyError prefers the table, else the server message', () => {
    expect(friendlyError('cancelled', 'x')).toBe('The download was cancelled.')
    expect(friendlyError('connection_lost', 'x')).toContain('connection')
    expect(friendlyError('something_new', 'Server says hi.')).toBe('Server says hi.')
  })
})
