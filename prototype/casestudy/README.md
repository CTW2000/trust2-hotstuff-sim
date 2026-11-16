# 案例：Aptos 上经过超时证书的分叉（DESIGN.md §15.37）

用 aptos-core 自带的孪生验证者测试框架，构造一次经过超时证书的分叉，比较"只看两侧账本"和"保留超时证书"两种情况下能指认谁。整个测试在一个进程里用模拟网络运行，不接触任何已部署的网络。

## 文件

- `aptos_twins_timeout_fork_test.rs`：测试本身，追加到 aptos-core 的 `consensus/src/twins/basic_twins_test.rs` 末尾。
- `aptos_env.sh`：实验室服务器上的构建环境。服务器没有管理员权限，也没有 lld、protoc 和 OpenSSL 的开发头文件，所以：
  - 开发头文件用 `apt download` 取官方软件包，`dpkg-deb -x` 解到 `~/opt/sysroot`，再用环境变量指给构建脚本；
  - protoc 用官方发布的二进制，放在 `~/opt/protoc`；
  - 不用仓库配置里的 lld 链接参数；
  - crate 经中国科学技术大学的 crates.io 镜像下载，校验和仍按仓库的 `Cargo.lock` 核对；git 依赖用系统的 git 命令拉取。

## 步骤

```bash
git clone --depth 1 https://github.com/aptos-labs/aptos-core.git   # 所用提交：8c2ed9702bb6b7849473bb5239db6dcf0c6bc0f8
cat aptos_twins_timeout_fork_test.rs >> aptos-core/consensus/src/twins/basic_twins_test.rs
source aptos_env.sh
cd aptos-core
cargo "${MIRROR[@]}" test --locked -p aptos-consensus twins_timeout_fork_test -- --ignored --nocapture
```
