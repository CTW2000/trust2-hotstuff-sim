# 案例：Aptos 上经过超时证书的分叉（DESIGN.md §15.37）

在 aptos-core 的安全规则模块上构造一次经过超时证书的分叉，比较"只看两侧账本"和"保留超时证书"两种情况下能指认谁。测试只在内存里构造块和证书，不接触任何已部署的网络。

## 文件

- `aptos_safety_rules_timeout_fork.rs`：测试本身。放到 aptos-core 的 `consensus/safety-rules/src/tests/twins_timeout_fork.rs`，并在同目录的 `mod.rs` 末尾加一行 `mod twins_timeout_fork;`。
- `aptos_env.sh`：实验室服务器上的构建环境。服务器没有管理员权限，也没有 lld、protoc、pkg-config 和 OpenSSL 等开发头文件，所以：
  - 开发头文件和 pkg-config 用 `apt download` 取官方软件包，`dpkg-deb -x` 解到 `~/opt/sysroot`，再用环境变量指给构建脚本；
  - protoc 用官方发布的二进制，放在 `~/opt/protoc`；
  - 不用仓库配置里的 lld 链接参数；
  - crate 经中国科学技术大学的 crates.io 镜像下载，校验和仍按仓库的 `Cargo.lock` 核对；git 依赖用系统的 git 命令拉取。镜像设置写在检出目录的 `.cargo/config.toml` 末尾，这样构建脚本内部调用的 cargo 也走镜像。

## 步骤

```bash
git clone --depth 1 https://github.com/aptos-labs/aptos-core.git   # 所用提交：8c2ed9702bb6b7849473bb5239db6dcf0c6bc0f8
cp aptos_safety_rules_timeout_fork.rs aptos-core/consensus/safety-rules/src/tests/twins_timeout_fork.rs
echo "mod twins_timeout_fork;" >> aptos-core/consensus/safety-rules/src/tests/mod.rs
source aptos_env.sh
cd aptos-core
cargo test --locked -p aptos-safety-rules twins_timeout_fork -- --nocapture
```

## 为什么没有用它的孪生验证者测试框架

最初的方案是用 `consensus/src/twins/` 下的完整节点测试框架。在这一提交上它已经无法启动：
- 框架给节点的链上配置里没有特性开关，纪元管理器启动时直接报错。补上这一项之后，
- 纪元管理器要向执行客户端要一个执行管线构造器，而测试用的模拟执行客户端没有实现这个接口。

上游把这个目录下的测试都标成了忽略。要修好它得给模拟组件补上整条执行管线，所以改为直接驱动安全规则模块：投票和超时都由未修改的 `SafetyRules` 实例经公开接口签出，孪生就是同一把密钥的第二个实例，带一份独立的安全状态。
