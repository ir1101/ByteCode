# Arrays and the % operator

# --- list literals, indexing, len and append ---
squares = [];
for i = 1; i <= 6; i = i + 1 {
    append(squares, i * i);
}
print squares;                     # [1, 4, 9, 16, 25, 36]
print len(squares);                # 6
print squares[2];                  # 9

# --- % gives the remainder: keep only the odd squares ---
odd = [];
for i = 0; i < len(squares); i = i + 1 {
    if squares[i] % 2 == 1 {
        append(odd, squares[i]);
    }
}
print odd;                         # [1, 9, 25]

# --- lists are passed by reference: the function changes the caller's list ---
func reverse(xs) {
    i = 0;
    j = len(xs) - 1;
    while i < j {
        t = xs[i];
        xs[i] = xs[j];
        xs[j] = t;
        i = i + 1;
        j = j - 1;
    }
}
reverse(odd);
print odd;                         # [25, 9, 1]

# --- sieve of Eratosthenes: primes below 30 ---
n = 30;
is_prime = [];
for i = 0; i < n; i = i + 1 {
    append(is_prime, 1);
}
for p = 2; p * p < n; p = p + 1 {
    if is_prime[p] {
        for k = p * p; k < n; k = k + p {
            is_prime[k] = 0;
        }
    }
}
primes = [];
for i = 2; i < n; i = i + 1 {
    if is_prime[i] {
        append(primes, i);
    }
}
print primes;                      # [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]

# --- a 2-D grid: a list of lists ---
grid = [[1, 2, 3], [4, 5, 6]];
grid[1][2] = 60;
print grid;                        # [[1, 2, 3], [4, 5, 60]]
print grid[0][1] + grid[1][2];     # 62
