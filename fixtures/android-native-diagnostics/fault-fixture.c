#define _GNU_SOURCE
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdint.h>
extern char fixture_fault[];
int main(void) {
    void *p = mmap((void *)0x12345000, 4096, PROT_READ,
                   MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED, -1, 0);
    if (p != (void *)0x12345000) return 2;
    printf("pid=%d address=%p operation=write32 value=0x13579bdf fault_pc=%p expected=c700df9b5713\n", getpid(), p, fixture_fault);
    fflush(stdout);
    sleep(2);
    __asm__ volatile("movabs $0x12345000, %%rax\n"
                     ".global fixture_fault\nfixture_fault:\n"
                     "movl $0x13579bdf, (%%rax)\n" ::: "rax", "memory");
    return 3;
}
