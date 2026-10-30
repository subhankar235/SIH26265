import { Stack, useLocalSearchParams } from 'expo-router';
import { Card, Screen, styles, Text } from '../../../components/ui';
import { useAuth } from '../../../providers/AuthProvider';
import { SCREEN_CONFIG } from '../../../lib/screens';
import RecordScreen from '../../../screens/RecordScreen';
import AssistantScreen from '../../../screens/AssistantScreen';
import CommandScreen from '../../../screens/CommandScreen';
import MobileIntelligence from '../../../screens/MobileIntelligence';
import PasswordScreen from '../../../screens/PasswordScreen';

const SPECIAL = {
  assistant: AssistantScreen,
  command: CommandScreen,
  'ml-governance': MobileIntelligence,
  password: PasswordScreen,
};

function Message({ title, body }) {
  return <Screen title={title}><Card><Text style={styles.muted}>{body}</Text></Card></Screen>;
}

export default function FeatureScreen() {
  const params = useLocalSearchParams();
  const screenKey = String(params.key || '');
  const definition = SCREEN_CONFIG[screenKey];
  const { user } = useAuth();

  if (!definition || !user) {
    return <Message title="Page unavailable" body="This mobile page is not configured."/>;
  }
  if (!definition.roles.includes(user.role)) {
    return <><Stack.Screen options={{ title: definition.title }}/>
      <Message title="Access unavailable" body="Your account is not permitted to open this page."/></>;
  }
  const Special = SPECIAL[screenKey];
  return <>
    <Stack.Screen options={{ title: definition.title }}/>
    {Special ? <Special/> : <RecordScreen screenKey={screenKey} definition={definition} user={user}/>}
  </>;
}
