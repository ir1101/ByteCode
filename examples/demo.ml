# MiniLang demo: variables, arithmetic, if/else, while, print, logic

x = 10;
y = 3;
print x + y * 2;        # 16
print (x - y) / 2;      # 3

if x > y and not (y == 0) {
    print 1;
} else {
    print 0;
}

# sum of 1..5 and factorial of 5
i = 1;
sum = 0;
fact = 1;
while i <= 5 {
    sum = sum + i;
    fact = fact * i;
    i = i + 1;
}
print sum;              # 15
print fact;             # 120

# countdown from 6, printing only even numbers
n = 6;
while n > 0 {
    if n / 2 * 2 == n {
        print n;
    } else {
        print -1;
    }
    n = n - 1;
}
