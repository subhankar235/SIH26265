import { Stack } from 'expo-router';
import { AuthProvider } from '../providers/AuthProvider';
import { colors } from '../components/ui';

export default function RootLayout() {
  return <AuthProvider><Stack screenOptions={{ headerStyle: { backgroundColor: colors.white },
    headerTintColor: colors.navy, headerTitleStyle: { fontWeight: '700' },
    contentStyle: { backgroundColor: colors.pale } }}>
    <Stack.Screen name="index" options={{ headerShown: false }}/>
    <Stack.Screen name="login" options={{ title: 'Sign in', headerShown: false }}/>
    <Stack.Screen name="mfa" options={{ title: 'Verify identity' }}/>
    <Stack.Screen name="change-password" options={{ title: 'Change password' }}/>
    <Stack.Screen name="(portal)" options={{ headerShown: false }}/>
  </Stack></AuthProvider>;
}
