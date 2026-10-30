import { router } from 'expo-router';
import { Text } from 'react-native';
import { Button, Card, Screen, styles } from '../components/ui';

export default function PasswordScreen() {
  return <Screen title="Change password" subtitle="Update the password you use to sign in to this portal.">
    <Card>
      <Text style={styles.muted}>You will be asked for your current password, then signed out of this device on success so the new password takes effect everywhere.</Text>
      <Button title="Open change password" onPress={() => router.push('/change-password')}/>
    </Card>
  </Screen>;
}
