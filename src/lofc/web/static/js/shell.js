// Behaviour common to every signed-in page: the Sign out link.
import {api} from './common.js';

const out = document.getElementById('signout');
if (out) out.addEventListener('click', async e => {
  e.preventDefault();
  try { await api('/logout', {method: 'POST'}); } catch { /* already signed out */ }
  window.location.href = '/login';
});
