# Functions, recursion, for loops, break and continue

# --- recursion: each call gets its own frame with its own `n` ---
func fact(n) {
    if n <= 1 {
        return 1;
    }
    return n * fact(n - 1);
}

func fib(n) {
    if n < 2 {
        return n;
    }
    return fib(n - 1) + fib(n - 2);
}

# --- mutual recursion: works because functions are collected before compiling ---
func is_even(n) {
    if n == 0 { return 1; }
    return is_odd(n - 1);
}

func is_odd(n) {
    if n == 0 { return 0; }
    return is_even(n - 1);
}

# --- a loop inside a function; t, a, b are locals of this call ---
func gcd(a, b) {
    while b != 0 {
        t = b;
        b = a - a / b * b;   # a mod b
        a = t;
    }
    return a;
}

print fact(5);               # 120

for i = 0; i < 10; i = i + 1 {
    print fib(i);            # 0 1 1 2 3 5 8 13 21 34
}

print gcd(48, 18);           # 6
print is_even(10);           # 1
print is_odd(7);             # 1

# --- continue skips to the update step; break leaves the loop ---
for i = 1; i < 100; i = i + 1 {
    if i / 2 * 2 == i {
        continue;            # skip even numbers
    }
    if i > 7 {
        break;               # stop after 7
    }
    print i;                 # 1 3 5 7
}

# --- a function can read globals; assigning inside it creates a local ---
limit = 3;
func below_limit(x) {
    limit = 100;             # local: the global `limit` is untouched
    return x < limit;
}
print below_limit(50);       # 1  (compared against the local 100)
print limit;                 # 3

# --- a call used as a statement: its return value is discarded ---
func show(x) {
    print x * 10;
}
show(4);                     # 40
