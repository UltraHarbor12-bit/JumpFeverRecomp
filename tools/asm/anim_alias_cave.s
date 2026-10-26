// getAnimation miss handler. Entry: w1 = missing hash, x6 = set+0x20.
// Tail-jumps back into getAnimation (absolute addresses patched in the literal pool).
    .text
    .globl cave
cave:
    adr  x2, table
1:  ldp  w3, w4, [x2], #8
    cbz  w3, 2f
    cmp  w1, w3
    b.ne 1b
    mov  w1, w4
    ldr  x0, [x6, #0x10]
    ldr  x16, lit_search
    br   x16
2:  ldr  w5, flag_fallback
    cbz  w5, 3f
    ldr  x4, [x6, #0x10]
    cbz  x4, 3f
    ldr  x0, [x4, #0x28]
    ldr  x16, lit_ret
    br   x16
3:  ldr  x0, lit_fmt
    ldr  x16, lit_fatal
    blr  x16
    mov  x0, #0
    ldr  x16, lit_ret
    br   x16
    .balign 8
lit_search: .quad 0x1002f32f8
lit_ret:    .quad 0x1002f333c
lit_fmt:    .quad 0x100511a00
lit_fatal:  .quad 0x1002fa4b4
flag_fallback: .word 0
    .balign 8
table:
