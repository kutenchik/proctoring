import test from 'node:test';
import assert from 'node:assert/strict';
import { renderToStaticMarkup } from 'react-dom/server';
import { DisconnectedScreen } from '../src/screens/DisconnectedScreen';

test('terminal backend message explains normal close and preserves pending evidence', () => {
  const html = renderToStaticMarkup(<DisconnectedScreen retry={() => {}} busy={false} reason="python_exited" />);
  assert.match(html, /Close the application normally/);
  assert.match(html, /Pending evidence is preserved/);
  assert.doesNotMatch(html, /<button/);
  const retryable = renderToStaticMarkup(<DisconnectedScreen retry={() => {}} busy={false} />);
  assert.match(retryable, /Reconnect to Python/);
});
