#include <jni.h>
#include <stdlib.h>

JNIEXPORT void JNICALL Java_dev_uitest_startup_StartupActivity_abortForTest(
        JNIEnv *env, jclass activity) {
    (void) env;
    (void) activity;
    abort();
}
