
// #include "StaticQueue.h" 

template<typename T, int N>
StaticQueue<T, N>::StaticQueue()
    : head(0), tail(0), count(0) {}

template<typename T, int N>
bool StaticQueue<T, N>::enqueue(const T& item, bool force) {
    if (isFull()){
        if (!force) return false;
        // overwrite oldest
        head = (head + 1) % N;
        count--;
    } 

    buffer[tail] = item;
    tail = (tail + 1) % N;
    count++;
    return true;
}

template<typename T, int N>
bool StaticQueue<T, N>::dequeue(T& out) {
    if (isEmpty()) return false;

    out = buffer[head];
    head = (head + 1) % N;
    count--;
    return true;
}

template<typename T, int N>
bool StaticQueue<T, N>::peek(T& out) const {
    if (isEmpty()) return false;

    out = buffer[head];
    return true;
}

template<typename T, int N>
T* StaticQueue<T, N>::front() {
    if (isEmpty()) return nullptr;
    return &buffer[head];
}

template<typename T, int N>
void StaticQueue<T, N>::pop() {
    if (isEmpty()) return;

    head = (head + 1) % N;
    count--;
}

template<typename T, int N>
bool StaticQueue<T, N>::isEmpty() const {
    return count == 0;
}

template<typename T, int N>
bool StaticQueue<T, N>::isFull() const {
    return count == N;
}

template<typename T, int N>
int StaticQueue<T, N>::size() const {
    return count;
}

template<typename T, int N>
int StaticQueue<T, N>::capacity() const {
    return N;
}

template<typename T, int N>
void StaticQueue<T, N>::clear() {
    head = tail = count = 0;
}
template<typename T, int N>
const T& StaticQueue<T, N>::at(int index) const {
    return buffer[(head + index) % N];
}
