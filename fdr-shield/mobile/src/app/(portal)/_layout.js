import { Stack, router } from 'expo-router';
import { useEffect } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';
import { useAuth } from '../../providers/AuthProvider';
import { colors, styles } from '../../components/ui';

export default function PortalLayout() {
  const { user, status } = useAuth();

  useEffect(() => {
    if (status === 'anonymous') router.replace('/login');
    else if (status === 'authenticated' && user?.must_change_password) router.replace('/change-password');
  }, [status, user]);

  if (status !== 'authenticated' || user?.must_change_password) {
    return <View style={[styles.root, { alignItems: 'center', justifyContent: 'center', gap: 10 }]}>
      <ActivityIndicator color={colors.blue}/>
      <Text style={styles.muted}>Opening your portal…</Text>
    </View>;
  }

  return <Stack screenOptions={{
    headerStyle: { backgroundColor: colors.white },
    headerTintColor: colors.navy,
    headerTitleStyle: { fontWeight: '700', fontSize: 15 },
    contentStyle: { backgroundColor: colors.pale },
  }}>
    <Stack.Screen name="index" options={{ headerShown: false }}/>
    <Stack.Screen name="screen/[key]" options={{ title: 'Portal' }}/>
    <Stack.Screen name="case/[id]" options={{ title: 'Case file' }}/>
    <Stack.Screen name="upload" options={{ title: 'Submit FDR' }}/>
  </Stack>;
}
