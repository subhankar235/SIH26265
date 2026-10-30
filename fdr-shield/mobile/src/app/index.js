import { useEffect } from 'react';
import { ActivityIndicator, Pressable, Text, View } from 'react-native';
import { router } from 'expo-router';
import { useAuth } from '../providers/AuthProvider';
import { colors, styles } from '../components/ui';

export default function IndexRoute() {
  const { status, user, restoreError, retry } = useAuth();
  useEffect(() => {
    if (status === 'anonymous') router.replace('/login');
    if (status === 'authenticated') router.replace(user?.must_change_password ? '/change-password' : '/(portal)');
  }, [status, user]);
  if (status === 'unavailable') return <View style={[styles.root,{justifyContent:'center',padding:24,gap:12}]}>
    <Text style={styles.title}>Sign-in service unavailable</Text><Text style={styles.subtitle}>{restoreError}</Text>
    <Pressable onPress={retry} style={styles.button}><Text style={styles.buttonText}>Try again</Text></Pressable>
  </View>;
  return <View style={[styles.root,{alignItems:'center',justifyContent:'center',gap:12}]}><ActivityIndicator color={colors.blue}/><Text style={styles.muted}>Restoring your secure session…</Text></View>;
}
