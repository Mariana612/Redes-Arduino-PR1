#ifndef HAMMING_H
#define HAMMING_H

inline unsigned char get_hamming_bits(unsigned char data) {
    unsigned char n;
    
    unsigned char response = 0;
    unsigned char masks[] = {91, 109, 142, 240};
    
    
    for (int i = 0; i < 4; i++) {
        n = masks[i];
        response = response << 1 |
            (__builtin_popcount(n & data) % 2);
    }
    
    return response;
}

inline int code_hamming(unsigned char data) {
  int hammingCode = 0;
  int powIndex = 0;
  int dataIndex = 0;
  
  unsigned char parity_bits = get_hamming_bits(data);
  int parity_bit;
  
  for (int i = 0; i < 12; i++) {
      
    if ((1 << powIndex) == i + 1) {
        parity_bit = parity_bits & 1;
        parity_bits >>= 1;
        powIndex++;
    } else {
    	parity_bit = (data>>dataIndex) & 1;
    	dataIndex++;
    }
    
	hammingCode = hammingCode | parity_bit <<i;
  }
  hammingCode = hammingCode | (__builtin_popcount(hammingCode) % 2) << 12; 
  return hammingCode;
}

#endif
