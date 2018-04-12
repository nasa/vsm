#include <curl/curl.h>
#include <string>
#include <iostream>
#include <sstream>

// CURL delivers all recieved data (the body of HTTP requests, in our case)
// to a callback function, which simply writes to the console by default.
// You probably don't want that, so define your own. A common implementation
// is to store the incomming data into a dynamically growing allocated buffer.
// You may not want that either. This one just ignores it.
// See https://curl.haxx.se/libcurl/c/CURLOPT_WRITEFUNCTION.html
// Example: https://curl.haxx.se/libcurl/c/getinmemory.html
size_t write_data(void *buffer, size_t size, size_t nmemb, void *userp) {
    return size * nmemb;
}

int main(int, char **) {

    // Instantiate CURL
    CURL* curl = curl_easy_init();
    if (!curl) {
        std::cout << "Failed to initialize CURL" << std::endl;
        return -1;
    }

    CURLcode result;

    // Set the callback function
    result = curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_data);
    if (result != CURLE_OK) {
        std::cout << curl_easy_strerror(result) << std::endl;
        return -1;
    }

    // Turn off all diagnostic printouts. Not sure if you want to do this.
    curl_easy_setopt(curl, CURLOPT_VERBOSE, 0L);
    if (result != CURLE_OK) {
        std::cout << curl_easy_strerror(result) << std::endl;
        return -1;
    }

    // This call will tell CURL to automatically follow redirects, which would
    // result in MJPEG data being constantly delivered to your callback
    // function. Since you already have code for dealing with that, you would
    // probably prefer to just get the redirected URL and handle going to it
    // yourself.
    /*curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    if (result != CURLE_OK) {
        std::cout << curl_easy_strerror(result) << std::endl;
        return -1;
    }*/

    const char* vsm_address = "localhost";
    const unsigned short vsm_port = 12345;

    // Get a line from the terminal
    std::string camera;
    std::cout << "Enter camera name: ";
    while (std::getline(std::cin, camera)) {

        // Build the URL
        std::ostringstream url;
        url << vsm_address << ":" << vsm_port << "/streams/" << camera.c_str();

        // Tell CURL what URL to GET
        result = curl_easy_setopt(curl, CURLOPT_URL, url.str().c_str());
        if (result != CURLE_OK) {
            std::cout << curl_easy_strerror(result) << std::endl;
            return -1;
        }

        // Perform the HTTP request
        result = curl_easy_perform(curl);
        if (result != CURLE_OK) {
            std::cout << curl_easy_strerror(result) << std::endl;
            return -1;
        }

        // Get the HTTP response code
        long response_code;
        result = curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &response_code);
        if (result != CURLE_OK) {
            std::cout << curl_easy_strerror(result) << std::endl;
            return -1;
        }

        switch (response_code) {
            case 307:
                // 307 is a redirect, get the location
                const char* location;
                result = curl_easy_getinfo(curl, CURLINFO_REDIRECT_URL, &location);
                if (result != CURLE_OK) {
                    std::cout << curl_easy_strerror(result) << std::endl;
                    return -1;
                }
                std::cout << "Redirected to: " << location << std::endl;
                break;

            case 404:
                // This camera does not exist in any EDGE instance.
                std::cout << "No such camera: " << camera.c_str() << std::endl;
                break;

            case 503:
                // This camera exists, but all EDGE instances capable of rendering it
                // are busy rendering other cameras for other clients. (We're out of
                // resources.)
                std::cout << "Camera unavailable: " << camera.c_str() << std::endl;
                break;

            default:
                std::cout << "Unhandled reponse code. Better ask Derek if the VSM changed!" << std::endl;
                break;
        }

        std::cout << "Enter camera name: ";
    }

    // Free resources
    curl_easy_cleanup(curl);

    return 0;
}
