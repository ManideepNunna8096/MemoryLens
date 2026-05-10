if (hasSession()) {
  window.location.href = 'pages/gallery.html';
}

function switchTab(tab) {
  document.querySelectorAll('.tab').forEach((item, index) => {
    const isActive = (index === 0 && tab === 'login') || (index === 1 && tab === 'register');
    item.classList.toggle('active', isActive);
  });

  document.getElementById('login-form').classList.toggle('active', tab === 'login');
  document.getElementById('register-form').classList.toggle('active', tab === 'register');
}

async function handleLogin() {
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;

  if (!email || !password) {
    showToast('Please fill all fields', 'error');
    return;
  }

  const buttonLabel = document.getElementById('login-btn-text');
  buttonLabel.innerHTML = '<span class="spinner"></span>';

  try {
    const data = await Auth.login(email, password);
    if (data.token) {
      setAuthTokens(data.access_token || data.token, data.refresh_token);
      localStorage.setItem('ml_user', JSON.stringify(data.user));
      showToast('Welcome back!', 'success');
      setTimeout(() => {
        window.location.href = 'pages/gallery.html';
      }, 800);
      return;
    }

    showToast(data.error || 'Login failed', 'error');
  } catch (error) {
    showToast(error.message || 'Login failed', 'error');
  }
  buttonLabel.textContent = 'Sign In';
}

async function handleRegister() {
  const name = document.getElementById('reg-name').value.trim();
  const email = document.getElementById('reg-email').value.trim();
  const password = document.getElementById('reg-password').value;

  if (!name || !email || !password) {
    showToast('Please fill all fields', 'error');
    return;
  }

  const buttonLabel = document.getElementById('reg-btn-text');
  buttonLabel.innerHTML = '<span class="spinner"></span>';

  try {
    const data = await Auth.register(name, email, password);
    if (data.token) {
      setAuthTokens(data.access_token || data.token, data.refresh_token);
      localStorage.setItem('ml_user', JSON.stringify(data.user));
      showToast('Account created!', 'success');
      setTimeout(() => {
        window.location.href = 'pages/gallery.html';
      }, 800);
      return;
    }

    showToast(data.error || 'Registration failed', 'error');
  } catch (error) {
    showToast(error.message || 'Registration failed', 'error');
  }
  buttonLabel.textContent = 'Create Account';
}

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter') {
    return;
  }

  const loginActive = document.getElementById('login-form').classList.contains('active');
  if (loginActive) {
    handleLogin();
    return;
  }

  handleRegister();
});
