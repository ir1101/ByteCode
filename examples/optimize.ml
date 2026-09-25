# Shows what the optimizer does. Compare:
#   python main.py examples/optimize.ml --debug --no-opt
#   python main.py examples/optimize.ml --debug

print 2 * 3 + 4;                # folded to PUSH 10
x = (100 - 1) / 9 * -1;         # folded to PUSH -11
print x;

if 0 {                          # branch never taken: removed entirely
    print 999;
} else {
    print 1;
}

while 0 {                       # loop never runs: removed entirely
    print 888;
}

print 1 or undefined_var;       # left side decides: folded to 1
print 0 and undefined_var;      # left side decides: folded to 0
print not (3 > 5);              # folded to 1

i = 3;
while i > 0 {
    i = i - 1;
    if i == 1 {                 # then-branch's "JUMP end" lands on the loop's
        print 10;               # "JUMP start", so it is threaded straight there
    } else {
        print 0;
    }
}
