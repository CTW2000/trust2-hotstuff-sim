# Environment for building aptos-core on the lab server without system-wide development packages.
source ~/.cargo/env
SYS=$HOME/opt/sysroot/usr
export CARGO_NET_GIT_FETCH_WITH_CLI=true
export CARGO_NET_RETRY=10
export RUSTFLAGS="--cfg tokio_unstable -C force-frame-pointers=yes -C force-unwind-tables=yes"
export OPENSSL_INCLUDE_DIR=$SYS/include
export OPENSSL_LIB_DIR=$SYS/lib/x86_64-linux-gnu
export C_INCLUDE_PATH=$SYS/include:$SYS/include/x86_64-linux-gnu
export CPLUS_INCLUDE_PATH=$C_INCLUDE_PATH
export LIBRARY_PATH=$SYS/lib/x86_64-linux-gnu
[ -x $HOME/opt/protoc/bin/protoc ] && export PROTOC=$HOME/opt/protoc/bin/protoc
MIRROR=(--config 'source.crates-io.replace-with="ustc"' --config 'source.ustc.registry="sparse+https://mirrors.ustc.edu.cn/crates.io-index/"')
