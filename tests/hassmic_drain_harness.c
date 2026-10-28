#include <assert.h>
#include "audio_mixer.c"
static int queued, polls, closed, flushed, drained;
static char buffer[3200];
MixerHandle MixerOpenRec(const char *t) {return (void*)1;}
MixerHandle MixerOpenPlay(unsigned r,unsigned c,unsigned b,const char*t){return (void*)1;}
void *MixerGetBufRec(MixerHandle h,int*s,unsigned*n){return 0;}
int MixerReleaseBufRec(MixerHandle h){return 0;}
void *MixerGetBufPlay(MixerHandle h,int*s,unsigned*n){*n=sizeof(buffer);return buffer;}
int MixerReleaseBufPlay(MixerHandle h,unsigned n){queued+=n;return 0;}
unsigned MixerGetRate(MixerHandle h){return 16000;}
unsigned MixerGetNumCh(MixerHandle h){return 1;}
unsigned MixerGetSampleSizeBits(MixerHandle h){return 16;}
unsigned MixerGetNumBytes(MixerHandle h){polls++; if(polls>=4)queued=0;return queued;}
int MixerDrain(MixerHandle h){drained++;return 0;}
int MixerFlush(MixerHandle h){flushed++;queued=0;return 0;}
int MixerClose(MixerHandle h){assert(!queued);closed++;return 0;}
int main(void){
 assert(play_open(16000,1)==0);assert(play_write(buffer,sizeof(buffer))==0);
 play_close(1);assert(drained==1&&polls>=4&&closed==1&&!flushed);
 polls=0;assert(play_open(16000,1)==0);play_write(buffer,sizeof(buffer));
 play_close(0);assert(flushed==1&&closed==2&&polls==0);
 return 0;
}
