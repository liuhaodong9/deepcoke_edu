<template>
  <div class="login_container">
    <div class="login_box">
      <!-- 标题 -->
      <div class="title-area">
        <h1 class="brand-title">DeepCoke</h1>
        <p class="brand-subtitle">焦化大语言智能问答与分析系统 V1.0</p>
      </div>

      <!-- 登录/注册 Tab 切换 -->
      <div class="tab-switch">
        <span :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</span>
        <span :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</span>
      </div>

      <!-- ===== 登录表单 ===== -->
      <el-form
        v-show="mode === 'login'"
        ref="loginFormRef"
        :model="loginForm"
        :rules="loginFormRules"
        label-width="0px"
        class="auth-form"
        @keyup.enter.native="login"
      >
        <el-form-item prop="username">
          <el-input v-model="loginForm.username" placeholder="请输入用户账号" prefix-icon="el-icon-user-solid"></el-input>
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="loginForm.password" placeholder="请输入用户密码" prefix-icon="el-icon-lock" show-password auto-complete="new-password"></el-input>
        </el-form-item>
        <div class="form-options">
          <label class="user-agreement">
            <input type="checkbox" v-model="agreeToTerms" />
            阅读并接受
            <a href="#" @click.prevent>用户协议</a>和<a href="#" @click.prevent>隐私政策</a>
          </label>
          <a href="#" class="forgot-link" @click.prevent="forgotPassword">忘记密码？</a>
        </div>
        <el-button class="submit-btn" type="primary" :loading="loginLoading" @click="login">登 录</el-button>
        <div class="switch-link">
          还没有账号？<a href="#" @click.prevent="switchMode('register')">立即注册</a>
        </div>
      </el-form>

      <!-- ===== 注册表单 ===== -->
      <el-form
        v-show="mode === 'register'"
        ref="registerFormRef"
        :model="registerForm"
        :rules="registerFormRules"
        label-width="0px"
        class="auth-form"
        @keyup.enter.native="register"
      >
        <el-form-item prop="username">
          <el-input v-model="registerForm.username" placeholder="设置用户账号（3-10个字符）" prefix-icon="el-icon-user-solid"></el-input>
        </el-form-item>
        <el-form-item prop="nickname">
          <el-input v-model="registerForm.nickname" placeholder="设置昵称（选填）" prefix-icon="el-icon-s-custom"></el-input>
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="registerForm.password" placeholder="设置密码（6-15个字符）" prefix-icon="el-icon-lock" show-password></el-input>
        </el-form-item>
        <el-form-item prop="confirmPassword">
          <el-input v-model="registerForm.confirmPassword" placeholder="确认密码" prefix-icon="el-icon-lock" show-password></el-input>
        </el-form-item>
        <div class="form-options">
          <label class="user-agreement">
            <input type="checkbox" v-model="agreeToTermsReg" />
            阅读并接受
            <a href="#" @click.prevent>用户协议</a>和<a href="#" @click.prevent>隐私政策</a>
          </label>
        </div>
        <el-button class="submit-btn" type="primary" :loading="registerLoading" @click="register">注 册</el-button>
        <div class="switch-link">
          已有账号？<a href="#" @click.prevent="switchMode('login')">返回登录</a>
        </div>
      </el-form>
    </div>

    <!-- 粒子背景 -->
    <div class="particles">
      <vue-particles class="login-bg" color="#B0B0B8" linesColor="#B0B0B8" :particlesNumber="150" shapeType="circle" clickMode="repulse" hoverMode="repulse"></vue-particles>
    </div>

    <!-- 右下角 Logo 和文字 -->
    <div class="company-logo">
      <img src="../assets/imgs/CompanyLogo.png" alt="Logo" />
      <div class="company-text">苏州龙泰氢一能源科技有限公司</div>
    </div>
  </div>
</template>

<script>
export default {
  data () {
    const validateConfirmPassword = (rule, value, callback) => {
      if (value !== this.registerForm.password) {
        callback(new Error('两次输入的密码不一致'))
      } else {
        callback()
      }
    }

    return {
      mode: 'login',
      agreeToTerms: false,
      agreeToTermsReg: false,
      loginLoading: false,
      registerLoading: false,
      apiBaseUrl: 'http://127.0.0.1:8000',

      // 登录表单
      loginForm: { username: '', password: '' },
      loginFormRules: {
        username: [
          { required: true, message: '请输入登录账号', trigger: 'blur' },
          { min: 3, max: 10, message: '长度在 3 到 10 个字符', trigger: 'blur' }
        ],
        password: [
          { required: true, message: '请输入登录密码', trigger: 'blur' },
          { min: 6, max: 15, message: '长度在 6 到 15 个字符', trigger: 'blur' }
        ]
      },

      // 注册表单
      registerForm: { username: '', nickname: '', password: '', confirmPassword: '' },
      registerFormRules: {
        username: [
          { required: true, message: '请设置用户账号', trigger: 'blur' },
          { min: 3, max: 10, message: '长度在 3 到 10 个字符', trigger: 'blur' }
        ],
        password: [
          { required: true, message: '请设置密码', trigger: 'blur' },
          { min: 6, max: 15, message: '长度在 6 到 15 个字符', trigger: 'blur' }
        ],
        confirmPassword: [
          { required: true, message: '请确认密码', trigger: 'blur' },
          { validator: validateConfirmPassword, trigger: 'blur' }
        ]
      }
    }
  },
  methods: {
    switchMode (newMode) {
      this.mode = newMode
    },
    login () {
      this.$refs.loginFormRef.validate(async (valid) => {
        if (!valid) return
        if (!this.agreeToTerms) {
          this.$message.warning('请先阅读并接受用户协议和隐私政策')
          return
        }

        this.loginLoading = true
        try {
          const res = await this.$http.post(`${this.apiBaseUrl}/login`, this.loginForm)
          if (res.status !== 200 || res.data === 'fail') {
            this.$message.error('用户名或密码错误！')
            return
          }

          this.$message.success('登录成功！')
          window.sessionStorage.setItem('token', res.data.token)
          window.sessionStorage.setItem('username', res.data.username)
          window.sessionStorage.setItem('nickname', res.data.nickname || res.data.username)

          this.$router.push({ name: 'Landing' })
        } catch (error) {
          this.$message.error('网络错误，请检查后端是否启动')
        } finally {
          this.loginLoading = false
        }
      })
    },
    register () {
      this.$refs.registerFormRef.validate(async (valid) => {
        if (!valid) return
        if (!this.agreeToTermsReg) {
          this.$message.warning('请先阅读并接受用户协议和隐私政策')
          return
        }

        this.registerLoading = true
        try {
          const res = await this.$http.post(`${this.apiBaseUrl}/register`, {
            username: this.registerForm.username,
            password: this.registerForm.password,
            nickname: this.registerForm.nickname
          })

          if (res.data.status === 'ok') {
            this.$message.success('注册成功，请登录！')
            this.loginForm.username = this.registerForm.username
            this.loginForm.password = ''
            this.mode = 'login'
          } else {
            this.$message.error(res.data.message || '注册失败')
          }
        } catch (error) {
          this.$message.error('网络错误，请稍后重试')
        } finally {
          this.registerLoading = false
        }
      })
    },
    forgotPassword () {
      this.$message.info('请联系管理员重置密码')
    }
  }
}
</script>

<style lang="less" scoped>
.login_container {
  background-image: url('../assets/imgs/DeepCokeBackground_2.png');
  background-repeat: no-repeat;
  height: 100%;
  background-size: 110% 100%;
}

/* ===== 登录/注册卡片 ===== */
.login_box {
  width: 480px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(20px);
  border-radius: 16px;
  border: 1px solid #D5D5DA;
  padding: 40px 36px 32px;
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(17%, -45%);
  z-index: 10;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
}

/* ===== 标题区域 ===== */
.title-area {
  text-align: center;
  margin-bottom: 28px;
}

.brand-title {
  font-family: 'Orbitron', sans-serif;
  font-size: 42px;
  font-weight: 900;
  margin: 0 0 8px;
  background: linear-gradient(90deg, #ff8a00, #149efa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.brand-subtitle {
  font-size: 14px;
  color: #64748B;
  margin: 0;
  letter-spacing: 2px;
}

/* ===== Tab 切换 ===== */
.tab-switch {
  display: flex;
  justify-content: center;
  gap: 0;
  margin-bottom: 24px;
  border-bottom: 1px solid #D5D5DA;

  span {
    flex: 1;
    text-align: center;
    padding: 10px 0;
    font-size: 16px;
    color: #94A3B8;
    cursor: pointer;
    transition: all 0.3s;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;

    &.active {
      color: #1E293B;
      font-weight: 600;
      border-bottom-color: #149efa;
    }

    &:hover:not(.active) {
      color: #64748B;
    }
  }
}

/* ===== 表单 ===== */
.auth-form {
  padding: 0;
}

/* 输入框样式穿透 */
::v-deep .el-input__inner {
  background: #E8E8ED;
  border: 1px solid #D5D5DA;
  color: #1E293B;
  border-radius: 8px;
  height: 42px;

  &::placeholder {
    color: #94A3B8;
  }

  &:focus {
    border-color: #149efa;
    background: #F0F0F3;
  }
}

::v-deep .el-input__prefix {
  color: #94A3B8;
}

/* 选项行：协议 + 忘记密码 */
.form-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.user-agreement {
  font-size: 12px;
  color: #64748B;
  display: flex;
  align-items: center;
  cursor: pointer;

  input[type="checkbox"] {
    margin-right: 6px;
    accent-color: #149efa;
  }

  a {
    color: #2563EB;
    text-decoration: none;
    margin: 0 2px;
  }
}

.forgot-link {
  font-size: 12px;
  color: #2563EB;
  text-decoration: none;
  white-space: nowrap;

  &:hover {
    text-decoration: underline;
  }
}

/* 提交按钮 */
.submit-btn {
  width: 100%;
  height: 44px;
  font-size: 16px;
  font-weight: 600;
  border-radius: 8px;
  letter-spacing: 6px;
  background: linear-gradient(135deg, #149efa, #0d6efd);
  border: none;
  margin-bottom: 16px;

  &:hover {
    background: linear-gradient(135deg, #3db2ff, #1a7cff);
  }

  &:active {
    transform: scale(0.98);
  }
}

/* 切换链接 */
.switch-link {
  text-align: center;
  font-size: 13px;
  color: #64748B;

  a {
    color: #2563EB;
    text-decoration: none;
    margin-left: 4px;

    &:hover {
      text-decoration: underline;
    }
  }
}

/* ===== 公司 Logo ===== */
.company-logo {
  position: fixed;
  bottom: 20px;
  right: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  z-index: 10;

  img {
    width: 170px;
    height: 50px;
    margin-bottom: 5px;
  }
}

.company-text {
  color: #1E293B;
  font-size: 14px;
  font-weight: bold;
}

/* 表单验证错误提示 */
::v-deep .el-form-item__error {
  color: #EF4444 !important;
  font-weight: 400 !important;
  font-size: 12px;
}

/* 减少表单项间距 */
::v-deep .el-form-item {
  margin-bottom: 18px;
}
</style>
