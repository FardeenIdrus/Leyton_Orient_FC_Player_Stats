// Forced / voluntary password change form (the POST needs the X-LOFC-Request header, which
// api() adds, so this is a fetch rather than a plain form post).
import {api} from './common.js';

const form = document.getElementById('pw-form'), err = document.getElementById('pw-error');
form.addEventListener('submit', async e => {
  e.preventDefault();
  err.hidden = true;
  try {
    await api('/api/change-password', {json: {
      password: document.getElementById('password').value,
      confirm: document.getElementById('confirm').value}});
    window.location.href = '/players';
  } catch (ex) {
    err.textContent = (ex.body && ex.body.error) || 'Could not set the password.';
    err.hidden = false;
  }
});
