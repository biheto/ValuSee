import { ArrowLeft, CheckCircle2, Loader2, LockKeyhole, Mail, RefreshCw, ShieldCheck, UserRound } from 'lucide-react';
import { FormEvent, useEffect, useRef, useState } from 'react';
import type React from 'react';
import { apiUrl } from './runtime';

type AuthMode = 'login' | 'register' | 'forgot' | 'reset';

async function authRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(String(body.detail ?? `请求失败：${response.status}`));
  }
  return response.json();
}

function redirectTarget() {
  const params = new URLSearchParams(window.location.search);
  const redirect = params.get('redirect');
  if (redirect?.startsWith('/') && !redirect.startsWith('//')) return redirect;
  return '/';
}

export function AuthPage() {
  const params = new URLSearchParams(window.location.search);
  const initialMode: AuthMode = params.get('reset_token') ? 'reset' : window.location.pathname.startsWith('/register') ? 'register' : params.get('mode') === 'forgot' ? 'forgot' : 'login';
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [resetToken, setResetToken] = useState(params.get('reset_token') || '');
  const [busy, setBusy] = useState(false);
  const [codeCooldown, setCodeCooldown] = useState(0);
  const [notice, setNotice] = useState('');
  const [noticeError, setNoticeError] = useState(false);
  const [captchaVersion, setCaptchaVersion] = useState(0);
  const [captchaId, setCaptchaId] = useState('');
  const [captchaImage, setCaptchaImage] = useState('');
  const [captchaCode, setCaptchaCode] = useState('');
  const captchaRequestKey = useRef('');
  const title = mode === 'login' ? '登录 ValuSee' : mode === 'register' ? '创建 ValuSee 账户' : mode === 'forgot' ? '找回密码' : '重置密码';
  const subtitle = mode === 'login' ? '进入你的购物决策、降价提醒和售后记录。' : mode === 'register' ? '验证邮箱后同步收藏、报告和监控数据。' : mode === 'forgot' ? '我们会向注册邮箱发送一次性重置链接。' : '请输入两次新密码完成更新。';

  useEffect(() => {
    if (codeCooldown <= 0) return;
    const timer = window.setInterval(() => setCodeCooldown((seconds) => Math.max(0, seconds - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [codeCooldown]);

  function switchMode(next: AuthMode) {
    setMode(next);
    setNotice('');
    setNoticeError(false);
    setPassword('');
    setConfirmPassword('');
    setVerificationCode('');
    setMfaCode('');
    setCaptchaCode('');
    setCaptchaId('');
    if (next !== 'reset') setResetToken('');
    window.history.replaceState({}, '', next === 'register' ? '/register' : next === 'forgot' ? '/login?mode=forgot' : '/login');
  }

  useEffect(() => {
    if (mode !== 'login' && mode !== 'register') return;
    const requestKey = `${mode}:${captchaVersion}`;
    if (captchaRequestKey.current === requestKey) return;
    captchaRequestKey.current = requestKey;
    setCaptchaCode('');
    setCaptchaId('');
    setCaptchaImage('');
    void authRequest<{ captcha_id: string; image: string }>('/api/v1/auth/captcha').then((result) => {
      if (captchaRequestKey.current !== requestKey) return;
      setCaptchaId(result.captcha_id);
      setCaptchaImage(result.image);
    }).catch(() => {
      if (captchaRequestKey.current === requestKey) setNotice('图形验证码加载失败，请点击刷新重试。');
    });
  }, [mode, captchaVersion]);

  async function requestCode() {
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setNotice('请先输入有效邮箱。');
      setNoticeError(true);
      return;
    }
    setBusy(true);
    setNotice('');
    setNoticeError(false);
    try {
      const result = await authRequest<{ retry_after?: number; verification_code?: string }>('/api/v1/auth/register/code/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      setCodeCooldown(result.retry_after || 60);
      if (result.verification_code) setVerificationCode(result.verification_code);
      setNotice('验证码已发送，10 分钟内有效。');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '验证码发送失败');
      setNoticeError(true);
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setNotice('');
    setNoticeError(false);
    try {
      if ((mode === 'login' || mode === 'register') && (!captchaId || !/^[A-Za-z0-9]{4,6}$/.test(captchaCode))) throw new Error('请输入图形验证码。');
      if ((mode === 'register' || mode === 'reset') && password !== confirmPassword) throw new Error('两次输入的密码不一致。');
      if (mode === 'register' && !/^\d{6}$/.test(verificationCode)) throw new Error('请输入邮箱中的 6 位验证码。');
      if (mode === 'forgot') {
        await authRequest('/api/v1/auth/password/reset/request', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email }),
        });
        setNotice('如果该邮箱已注册，重置邮件将发送到邮箱。');
        return;
      }
      if (mode === 'reset') {
        await authRequest('/api/v1/auth/password/reset/confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: resetToken, new_password: password, confirm_password: confirmPassword }),
        });
        setNotice('密码已更新，请使用新密码登录。');
        setMode('login');
        window.history.replaceState({}, '', '/login');
        return;
      }
      const path = mode === 'register' ? '/api/v1/auth/register' : '/api/v1/auth/login';
      const result = await authRequest<{ access_token: string; user: { display_name: string } }>(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          password,
          confirm_password: confirmPassword,
          verification_code: verificationCode,
          captcha_id: captchaId,
          captcha_code: captchaCode,
          display_name: displayName,
          mfa_code: mfaCode,
        }),
      });
      localStorage.setItem('valuesee-token', result.access_token);
      localStorage.setItem('valuesee-account-name', result.user.display_name || email);
      window.location.href = redirectTarget();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '账户操作失败');
      setNoticeError(true);
      if (mode === 'login' || mode === 'register') {
        setCaptchaCode('');
        setCaptchaVersion((value) => value + 1);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <a className="auth-back" href="/">
        <ArrowLeft size={16} />
        返回 ValuSee
      </a>
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-brand">
          <img src="/brand/logo-icon.png" alt="" />
          <div>
            <strong>ValuSee</strong>
            <span>AI 购物决策与省钱助手</span>
          </div>
        </div>
        <header className="auth-card-head">
          <span><ShieldCheck size={15} />账户中心</span>
          <h1 id="auth-title">{title}</h1>
          <p>{subtitle}</p>
        </header>
        <form className="auth-form" onSubmit={submit}>
          {mode === 'register' && <AuthField icon={<UserRound size={16} />} label="昵称" value={displayName} onChange={setDisplayName} autoComplete="name" />}
          {mode !== 'reset' && <AuthField icon={<Mail size={16} />} label="邮箱" type="email" required value={email} onChange={setEmail} autoComplete="email" />}
          {mode === 'register' && (
            <label className="auth-code-field">
              <span>邮箱验证码</span>
              <div>
                <input required inputMode="numeric" pattern="\d{6}" maxLength={6} value={verificationCode} onChange={(event) => setVerificationCode(event.target.value.replace(/\D/g, '').slice(0, 6))} />
                <button type="button" disabled={busy || codeCooldown > 0} onClick={requestCode}>{codeCooldown > 0 ? `${codeCooldown}s` : '获取验证码'}</button>
              </div>
            </label>
          )}
          {mode !== 'forgot' && <AuthField icon={<LockKeyhole size={16} />} label={mode === 'reset' ? '新密码' : '密码'} type="password" required minLength={8} value={password} onChange={setPassword} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />}
          {(mode === 'register' || mode === 'reset') && <AuthField icon={<LockKeyhole size={16} />} label="确认密码" type="password" required minLength={8} value={confirmPassword} onChange={setConfirmPassword} autoComplete="new-password" />}
          {mode === 'login' && <AuthField icon={<ShieldCheck size={16} />} label="动态验证码或恢复码" value={mfaCode} onChange={setMfaCode} autoComplete="one-time-code" optional />}
          {(mode === 'login' || mode === 'register') && <CharacterCaptcha image={captchaImage} value={captchaCode} onChange={setCaptchaCode} onReset={() => setCaptchaVersion((value) => value + 1)} />}
          {notice && <div className={`auth-notice${noticeError ? ' error' : ''}`}>{notice}</div>}
          <button className="auth-submit" disabled={busy || ((mode === 'login' || mode === 'register') && (!captchaId || !/^[A-Za-z0-9]{4,6}$/.test(captchaCode)))}>
            {busy ? <Loader2 className="spin" size={17} /> : mode === 'login' ? <ShieldCheck size={17} /> : <CheckCircle2 size={17} />}
            {busy ? '处理中' : mode === 'login' ? '登录' : mode === 'register' ? '注册并登录' : mode === 'forgot' ? '发送重置邮件' : '更新密码'}
          </button>
        </form>
        <div className="auth-switch">
          {mode === 'login' && <><button onClick={() => switchMode('register')}>创建账户</button><button onClick={() => switchMode('forgot')}>忘记密码</button></>}
          {mode !== 'login' && <button onClick={() => switchMode('login')}>返回登录</button>}
        </div>
      </section>
    </main>
  );
}

function AuthField({ label, icon, value, onChange, optional, ...props }: { label: string; icon: React.ReactNode; value: string; onChange: (value: string) => void; optional?: boolean } & Omit<React.InputHTMLAttributes<HTMLInputElement>, 'onChange' | 'value'>) {
  return (
    <label className="auth-field">
      <span>{label}{optional && <em>可选</em>}</span>
      <div>{icon}<input {...props} value={value} onChange={(event) => onChange(event.target.value)} /></div>
    </label>
  );
}

function CharacterCaptcha({ image, value, onChange, onReset }: { image: string; value: string; onChange: (value: string) => void; onReset: () => void }) {
  return (
    <div className="character-captcha">
      <div className="character-captcha-head"><span>图形验证码</span><small>请输入图片中的 4-6 位数字或字母</small></div>
      <div className="character-captcha-row">
        {image ? <img src={image} alt="图形验证码" /> : <div className="character-captcha-loading">正在生成...</div>}
        <button type="button" title="刷新验证码" aria-label="刷新验证码" onClick={onReset}><RefreshCw size={15} /></button>
      </div>
      <input aria-label="图形验证码输入" value={value} maxLength={6} autoComplete="off" spellCheck={false} onChange={(event) => onChange(event.target.value.replace(/[^a-zA-Z0-9]/g, '').slice(0, 6))} placeholder="输入验证码" />
    </div>
  );
}
