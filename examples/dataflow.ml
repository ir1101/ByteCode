# Data-flow analysis, dead stores and tail calls.
# Open the IR tab: every block lists the variables that are live on
# entry and exit. The "Optimized" view strikes out the dead stores.

width = 6;
height = 7;
area = width * height;          # constant propagation: area is 42
print area;                     # now nothing reads width, height or area,
                                # so all three stores are dead and removed

total = 0;
for i = 1; i <= 10; i += 1 {    # i += 1 is shorthand for i = i + 1
    total += i;
}
print total;

# Tail recursion: the recursive call is the last thing sum_to() does,
# so the optimizer turns CALL + RET into TAIL_CALL and reuses one frame.
# 5000 nested calls would pass the 1000-call limit. Compare with:
#   python main.py examples/dataflow.ml --no-opt
func sum_to(n, acc) {
    if n == 0 { return acc; }
    return sum_to(n - 1, acc + n);
}
print sum_to(5000, 0);

func gcd(a, b) {
    if b == 0 { return a; }
    return gcd(b, a % b);
}
print gcd(1071, 462);
