#ifndef _WIFISERVER_H_
#define _WIFISERVER_H_

#include "api/Server.h"
#include "WiFiClient.h"
#include "api/IPAddress.h"
#include "tal_log.h"
class WiFiServer : public Server {
  private:
    volatile bool _newClientAvailable = false;
    IPAddress _addr;
    uint16_t _port;
    uint8_t _max_clients;
    bool _listening;
    bool _noDelay = false;

  public:
    int sockfd;
    volatile int _accepted_sockfd = -1;
    using Server::begin;

    void listenOnLocalhost(){}

    // _addr(INADDR_ANY) is the same as _addr() ==> 0.0.0.0
    WiFiServer(uint16_t port=80, uint8_t max_clients=4):_addr(),_port(port),_max_clients(max_clients),_listening(false),_noDelay(false),sockfd(-1),_accepted_sockfd(-1) {
      PR_INFO("WiFiServer::WiFiServer(port=%d, ...)\r\n", port);
    }
    WiFiServer(const IPAddress& addr, uint16_t port=80, uint8_t max_clients=4):_addr(addr),_port(port),_max_clients(max_clients),_listening(false),_noDelay(false),sockfd(-1),_accepted_sockfd(-1) {
      PR_INFO("WiFiServer::WiFiServer(addr=%s, port=%d, ...)\r\n", addr.toString().c_str(), port);
    }
    ~WiFiServer(){ end();}
    bool startAcceptTask();
    WiFiClient available();
    WiFiClient accept(){return available();}
    bool begin( ){ return begin(0); };
    bool begin(uint16_t port=0);
    bool begin(uint16_t port, int reuse_enable);
    void setNoDelay(bool nodelay);
    bool getNoDelay();
    bool hasClient();
    size_t write(const uint8_t *data, size_t len);
    size_t write(uint8_t data){
      return write(&data, 1);
    }
    using Print::write;

    void end();
    void close();
    void stop();
    operator bool(){return _listening;}
    int setTimeout(uint32_t seconds);
    void stopAll();
};

#endif 