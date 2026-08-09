/* Aris C 扩展最小示例（占位）。
 *
 * 命名规范（见 AGENTS.md）：
 *   函数：大驼峰（ArisDemoAdd）；变量：小驼峰（userCount）；
 *   指针声明：星号靠变量（int *p）；常量/宏：UPPER_SNAKE_CASE。
 * 编译（Termux / Linux 均可用 cc）：
 *   cc -shared -fPIC -O2 -o demo.so demo.c
 * 产物 demo.so 被同目录 __init__.py 用 ctypes 加载。
 * 未来性能敏感的计算（向量、音频处理）在此扩展。
 */

#include <stdint.h>

/* 两个整数求和，演示 C 函数被 Python 调用 */
int64_t ArisDemoAdd(int64_t a, int64_t b) {
    return a + b;
}
