#pragma once

template<typename T, int N>
class StaticQueue {
public:
    StaticQueue();

    bool enqueue(const T& item);
    bool dequeue(T& out);
    bool peek(T& out) const;

    T* front();
    void pop();

    bool isEmpty() const;
    bool isFull() const;
    int  size() const;
    int  capacity() const;

    void clear();

private:
    T buffer[N];
    int head;
    int tail;
    int count;
};

#include "StaticQueue.tpp"
